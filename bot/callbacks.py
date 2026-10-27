from aiogram.filters.callback_data import CallbackData


class LangCb(CallbackData, prefix="lang"):
    code: str


class FloorPickCb(CallbackData, prefix="fpick"):
    role_id: int
    floor_id: int  # 0 = all floors


class CallCb(CallbackData, prefix="call"):
    action: str  # "acc" | "done" | "close"
    call_id: int


class AnnCb(CallbackData, prefix="ann"):
    action: str  # "all" | "grade" | "grp" | "pin" | "send" | "cancel"
    value: int = 0


class AnnDelCb(CallbackData, prefix="anndel"):
    ann_id: int
