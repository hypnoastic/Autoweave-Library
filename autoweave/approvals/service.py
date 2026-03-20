"""Human loop and approval helpers."""

from __future__ import annotations

from dataclasses import dataclass

from autoweave.models import ApprovalRequestRecord, HumanRequestRecord
from autoweave.orchestration.state import WorkflowRunState


@dataclass(slots=True)
class HumanLoopService:
    """Thin service facade for human requests and approvals."""

    state: WorkflowRunState

    def request_clarification(
        self,
        *,
        task_id: str,
        task_attempt_id: str,
        question: str,
        context_summary: str,
    ) -> HumanRequestRecord:
        return self.state.request_clarification(
            task_id=task_id,
            task_attempt_id=task_attempt_id,
            question=question,
            context_summary=context_summary,
        )

    def answer_clarification(self, request_id: str, *, answer_text: str, answered_by: str) -> HumanRequestRecord:
        return self.state.answer_human_request(
            request_id,
            answer_text=answer_text,
            answered_by=answered_by,
        )

    def request_approval(
        self,
        *,
        task_id: str,
        task_attempt_id: str,
        approval_type: str,
        reason: str,
    ) -> ApprovalRequestRecord:
        return self.state.request_approval(
            task_id=task_id,
            task_attempt_id=task_attempt_id,
            approval_type=approval_type,
            reason=reason,
        )

    def resolve_approval(self, request_id: str, *, approved: bool, resolved_by: str) -> ApprovalRequestRecord:
        return self.state.resolve_approval(
            request_id,
            approved=approved,
            resolved_by=resolved_by,
        )
