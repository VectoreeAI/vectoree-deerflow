"""Internal endpoint that stores Vectoree credentials inside this container."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.authz import _is_internal_caller
from app.gateway.vectoree_project import publish_vectoree_project

router = APIRouter(prefix="/api/internal/vectoree", tags=["vectoree"])


class ProjectCredentials(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_url: str = Field(alias="apiUrl")
    api_key: str = Field(alias="apiKey")
    api_base: str = Field(alias="apiBase")
    access_token: str = Field(alias="accessToken")
    refresh_token: str | None = Field(default=None, alias="refreshToken")
    project_id: str = Field(alias="projectId")
    project_name: str | None = Field(default=None, alias="projectName")
    key_id: str | None = Field(default=None, alias="keyId")


class ProjectCredentialsResponse(BaseModel):
    ok: bool


@router.post("/project-credentials", response_model=ProjectCredentialsResponse)
def save_project_credentials(body: ProjectCredentials, request: Request) -> ProjectCredentialsResponse:
    user = getattr(request.state, "user", None)
    if not _is_internal_caller(request, user):
        raise HTTPException(status_code=403, detail="Internal credentials required")
    credentials = {
        "apiUrl": body.api_url,
        "apiKey": body.api_key,
        "apiBase": body.api_base,
        "accessToken": body.access_token,
        "projectId": body.project_id,
    }
    if body.refresh_token:
        credentials["refreshToken"] = body.refresh_token
    if body.project_name:
        credentials["projectName"] = body.project_name
    if body.key_id:
        credentials["keyId"] = body.key_id
    try:
        publish_vectoree_project(credentials)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProjectCredentialsResponse(ok=True)
