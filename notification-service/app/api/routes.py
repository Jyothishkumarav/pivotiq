from fastapi import APIRouter, HTTPException, Request, status

from app.models.notification import (
    NotificationAcceptedResponse,
    NotificationRequest,
    NotificationStatusResponse,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.post("", response_model=NotificationAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
def send_notification(payload: NotificationRequest, request: Request) -> NotificationAcceptedResponse:
    service = request.app.state.notification_service
    return service.accept(payload)


@router.get("/{notf_req_id}", response_model=NotificationStatusResponse)
def get_notification_status(notf_req_id: str, request: Request) -> NotificationStatusResponse:
    service = request.app.state.notification_service
    result = service.get_status(notf_req_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="notification request not found")
    return result
