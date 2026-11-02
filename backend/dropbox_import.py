"""Dropbox import routes: closed-by-default connector skeleton.

Status is readable signed in; authorize and callback refuse with 503
until the owner configures the Dropbox app. No provider HTTP exists
on any path, so every route runs green keyless with zero network.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from backend import auth, store
from launchcrew import dropbox_import as dropbox_mod

router = APIRouter(prefix='/api/dropbox-import')


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class DropboxStatusOut(Strict):
    available: bool
    configured: bool
    live_verified: bool = False
    reason: str
    callback_path: str
    setup_names: list[str]


@router.get('/status', response_model=DropboxStatusOut)
def dropbox_status(actor: str = Depends(auth.actor)):
    """Return Dropbox connector status without leaking any values."""
    store.workspace_for_actor(actor)
    return dropbox_mod.status_dict()


@router.get('/authorize')
def dropbox_authorize(actor: str = Depends(auth.actor)):
    """Refuse closed until the owner configures the Dropbox app."""
    store.workspace_for_actor(actor)
    raise HTTPException(503, dropbox_mod.NOT_CONFIGURED_MESSAGE)


@router.get('/callback')
def dropbox_callback(actor: str = Depends(auth.actor)):
    """Refuse closed until the owner configures the Dropbox app."""
    store.workspace_for_actor(actor)
    raise HTTPException(503, dropbox_mod.NOT_CONFIGURED_MESSAGE)
