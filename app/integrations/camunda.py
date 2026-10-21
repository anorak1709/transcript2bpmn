"""Send a map to Camunda 8 (SaaS) Web Modeler as a BPMN file.

Uses the Web Modeler REST API with a client-credentials token: create a Web Modeler API client
in the Camunda Console (scope: Web Modeler, create/update), and set CAMUNDA_CLIENT_ID,
CAMUNDA_CLIENT_SECRET and CAMUNDA_PROJECT_ID (the Web Modeler project to file maps into).

UNTESTED against a live Camunda account: written to Camunda's documented API (token from
login.cloud.camunda.io, `POST /api/v1/files`); verify with a trial account before relying on it.
"""

from dataclasses import dataclass

import httpx

from app.core.config import get_settings


class CamundaError(RuntimeError):
    pass


@dataclass
class Pushed:
    file_id: str
    url: str


def configured() -> bool:
    s = get_settings()
    return bool(s.camunda_client_id and s.camunda_client_secret and s.camunda_project_id)


def _token(client: httpx.Client) -> str:
    s = get_settings()
    r = client.post(
        s.camunda_oauth_url,
        data={
            "grant_type": "client_credentials",
            "audience": s.camunda_audience,
            "client_id": s.camunda_client_id,
            "client_secret": s.camunda_client_secret,
        },
    )
    if r.status_code != 200:
        raise CamundaError(f"Camunda refused the credentials ({r.status_code}). Check the client ID and secret.")
    return str(r.json()["access_token"])


def push(name: str, bpmn_xml: str) -> Pushed:
    """Create the diagram as a new file in the configured Web Modeler project."""
    if not configured():
        raise CamundaError("Camunda isn't set up on this server")
    s = get_settings()
    base = s.camunda_modeler_url.rstrip("/")
    with httpx.Client(timeout=30) as client:
        token = _token(client)
        r = client.post(
            f"{base}/api/v1/files",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": name, "projectId": s.camunda_project_id, "content": bpmn_xml, "fileType": "bpmn"},
        )
    if r.status_code not in (200, 201):
        raise CamundaError(f"Camunda didn't accept the diagram ({r.status_code}): {r.text[:200]}")
    file_id = str(r.json().get("id", ""))
    return Pushed(file_id=file_id, url=f"{base}/diagrams/{file_id}")
