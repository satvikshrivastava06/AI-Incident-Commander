"""
Incident Engine
------------------
YOUR platform's own record of incidents it has recognized in the
system it monitors.

Exposes:
  - GET /health              -> liveness check (UNAUTHENTICATED, see Why)
  - POST /incidents          -> create a new incident (requires X-API-Key)
  - GET /incidents           -> list incidents (requires X-API-Key)
  - GET /incidents/{id}      -> fetch a single incident (requires X-API-Key)
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from models import AsyncSessionLocal, Incident, init_models, require_env

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("incident-engine")

API_KEY = require_env("API_KEY")

app = FastAPI(
    title="Incident Engine",
    description="Tracks incidents recognized by the AI Incident Commander platform.",
    version="0.4.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def verify_api_key(x_api_key: str = Header(...)) -> None:
    """
    Minimal service-to-service authentication: every caller must send
    a shared secret in the X-API-Key header, checked against this
    process's own API_KEY. NOT real per-user authentication -- no
    identity, no per-caller permissions, one shared secret for every
    legitimate caller. This is the baseline fix for "this API had zero
    auth and anyone who could reach the port could read/write incident
    data." Real user-facing login (needed for the dashboard before any
    real customer sees it) is separate, larger work that depends on
    picking an identity provider -- explicitly out of scope here.
    """
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


class IncidentCreate(BaseModel):
    service_name: str = Field(..., description="Which service this incident concerns")
    title: str = Field(..., description="Short, human-readable incident summary")
    description: Optional[str] = Field(default=None, description="Longer free-text detail")
    severity: str = Field(default="medium", description="low | medium | high | critical")
    detected_at: Optional[datetime] = Field(default=None, description="Defaults to now if omitted")
    related_deployment_id: Optional[UUID] = Field(default=None, description="Optional link to a Deployment")


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    service_name: str
    title: str
    description: Optional[str]
    severity: str
    status: str
    detected_at: datetime
    resolved_at: Optional[datetime]
    created_at: datetime
    related_deployment_id: Optional[UUID]


@app.on_event("startup")
async def startup():
    await init_models()
    logger.info("Incident Engine started; tables verified/created.")


@app.get("/health")
def health_check():
    # Deliberately UNAUTHENTICATED: health checks need to be callable
    # by monitoring systems (and, once deployed for real, Kubernetes'
    # own probes) without a credential -- standard practice, and it
    # leaks no sensitive data.
    return {
        "status": "healthy",
        "service": "incident-engine",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/incidents", response_model=IncidentRead, dependencies=[Depends(verify_api_key)])
async def create_incident(payload: IncidentCreate, response: Response):
    async with AsyncSessionLocal() as session:
        existing_query = select(Incident).where(
            Incident.service_name == payload.service_name,
            Incident.status == "open",
        )
        existing_result = await session.execute(existing_query)
        existing_incident = existing_result.scalars().first()

        if existing_incident is not None:
            response.status_code = 200
            return existing_incident

        response.status_code = 201
        incident = Incident(
            service_name=payload.service_name,
            title=payload.title,
            description=payload.description,
            severity=payload.severity,
            detected_at=payload.detected_at or datetime.utcnow(),
            related_deployment_id=payload.related_deployment_id,
        )
        session.add(incident)
        await session.commit()
        await session.refresh(incident)
        return incident


@app.get("/incidents", response_model=list[IncidentRead], dependencies=[Depends(verify_api_key)])
async def list_incidents(
    status: Optional[str] = Query(default=None, description="Filter by status, e.g. 'open'"),
    service_name: Optional[str] = Query(default=None, description="Filter by service name"),
):
    async with AsyncSessionLocal() as session:
        query = select(Incident).order_by(Incident.detected_at.desc())
        if status is not None:
            query = query.where(Incident.status == status)
        if service_name is not None:
            query = query.where(Incident.service_name == service_name)

        result = await session.execute(query)
        return result.scalars().all()


@app.get("/incidents/{incident_id}", response_model=IncidentRead, dependencies=[Depends(verify_api_key)])
async def get_incident(incident_id: UUID):
    async with AsyncSessionLocal() as session:
        incident = await session.get(Incident, incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")
        return incident


class IncidentResolveRequest(BaseModel):
    confirmed_root_cause: str


@app.post("/incidents/{incident_id}/resolve", response_model=IncidentRead, dependencies=[Depends(verify_api_key)])
async def resolve_incident(incident_id: UUID, payload: IncidentResolveRequest):
    """Resolves an incident, records confirmed root cause, and updates prediction accuracy."""
    import json
    from models import RootCausePrediction
    async with AsyncSessionLocal() as session:
        incident = await session.get(Incident, incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

        incident.status = "resolved"
        incident.resolved_at = datetime.utcnow()
        incident.confirmed_root_cause = payload.confirmed_root_cause

        result = await session.execute(
            select(RootCausePrediction).where(RootCausePrediction.incident_id == incident_id)
        )
        predictions = result.scalars().all()
        for pred in predictions:
            try:
                ranked = json.loads(pred.ranked_causes_json)
                top_predicted = ranked[0].get("service_name") if ranked else None
                pred.was_correct = (top_predicted == payload.confirmed_root_cause)
            except Exception:
                pass

        await session.commit()
        await session.refresh(incident)
        return incident


@app.get("/accuracy", dependencies=[Depends(verify_api_key)])
async def get_accuracy():
    """Returns accuracy metrics for root cause predictions."""
    from models import RootCausePrediction
    async with AsyncSessionLocal() as session:
        total = (await session.execute(select(func.count(RootCausePrediction.id)))).scalar() or 0
        correct = 0
        if total > 0:
            correct = (await session.execute(
                select(func.count(RootCausePrediction.id)).where(
                    RootCausePrediction.was_correct == True
                )
            )).scalar() or 0
    return {
        "total_predictions": total,
        "correct_predictions": correct,
        "accuracy": round(correct / total, 4) if total > 0 else None,
    }


@app.get("/deployment-info", dependencies=[Depends(verify_api_key)])
async def get_deployment_info():
    """Returns the latest deployments per service."""
    from models import Deployment
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Deployment).order_by(Deployment.deployed_at.desc()).limit(20)
        )
        deployments = result.scalars().all()
    return [
        {
            "id": str(d.id),
            "service_name": d.service_name,
            "version": d.version,
            "deployed_at": d.deployed_at.isoformat(),
        }
        for d in deployments
    ]


@app.post("/incidents/{incident_id}/predictions", dependencies=[Depends(verify_api_key)])
async def record_prediction(incident_id: UUID, payload: dict):
    """Records a root cause prediction for an incident."""
    import json
    from models import RootCausePrediction
    async with AsyncSessionLocal() as session:
        prediction = RootCausePrediction(
            incident_id=incident_id,
            ranked_causes_json=json.dumps(payload.get("ranked_causes", [])),
        )
        session.add(prediction)
        await session.commit()
        await session.refresh(prediction)
    return {"prediction_id": str(prediction.id), "incident_id": str(incident_id)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8007)