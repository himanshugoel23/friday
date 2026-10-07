"""TaskType -> AutonomyCategory, shared by the task and proactive engines."""

from __future__ import annotations

from friday.core.models import AutonomyCategory, AutonomyLevel, AutonomySetting, TaskType

_CATEGORY: dict[TaskType, AutonomyCategory] = {
    TaskType.BOOKING: AutonomyCategory.BOOKINGS,
    TaskType.RESCHEDULE: AutonomyCategory.BOOKINGS,
    TaskType.CANCEL_BOOKING: AutonomyCategory.BOOKINGS,
    TaskType.ORDER: AutonomyCategory.BOOKINGS,
    TaskType.HEALTHCARE: AutonomyCategory.BOOKINGS,
    TaskType.HOTEL_BOOKING: AutonomyCategory.BOOKINGS,
    TaskType.RECURRING_BOOKING: AutonomyCategory.ROUTINES,
    TaskType.DISCOVERY: AutonomyCategory.BOOKINGS,
    TaskType.ENQUIRY: AutonomyCategory.ENQUIRIES,
    TaskType.QUOTE: AutonomyCategory.ENQUIRIES,
    TaskType.STOCK_HUNT: AutonomyCategory.ENQUIRIES,
    TaskType.RENTAL_HUNT: AutonomyCategory.ENQUIRIES,
    TaskType.RECONFIRM: AutonomyCategory.FOLLOW_UPS,
    TaskType.RUNNING_LATE: AutonomyCategory.FOLLOW_UPS,
    TaskType.SERVICE_COORDINATION: AutonomyCategory.FOLLOW_UPS,
    TaskType.STATUS_CHASE: AutonomyCategory.FOLLOW_UPS,
    TaskType.COMPLAINT: AutonomyCategory.FOLLOW_UPS,
    TaskType.CUSTOMER_CARE: AutonomyCategory.FOLLOW_UPS,
    TaskType.WELLBEING_CHECKIN: AutonomyCategory.FAMILY,
}


def category_for(task_type: TaskType) -> AutonomyCategory:
    return _CATEGORY.get(task_type, AutonomyCategory.BOOKINGS)


def autonomy_for(
    settings: list[AutonomySetting], category: AutonomyCategory
) -> AutonomySetting | None:
    return next((s for s in settings if s.category == category), None)


def level_for(settings: list[AutonomySetting], category: AutonomyCategory) -> AutonomyLevel:
    """Effective level; SUGGEST is the default for every category (US-10.1)."""
    s = autonomy_for(settings, category)
    return s.level if s else AutonomyLevel.SUGGEST
