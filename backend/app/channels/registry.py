from app.channels.base import ChannelAdapter
from app.channels.whatsapp import WhatsAppCloudAdapter
from app.core.config import get_settings

_override: dict[str, ChannelAdapter] = {}


def get_adapter(channel: str = "whatsapp") -> ChannelAdapter:
    if channel in _override:
        return _override[channel]
    if channel == "whatsapp":
        return WhatsAppCloudAdapter(get_settings())
    raise ValueError(f"Канал {channel} не поддерживается")


def set_adapter_override(channel: str, adapter: ChannelAdapter | None) -> None:
    """Для тестов."""
    if adapter is None:
        _override.pop(channel, None)
    else:
        _override[channel] = adapter
