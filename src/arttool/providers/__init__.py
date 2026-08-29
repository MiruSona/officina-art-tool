"""제공자 등록. 여기서만 제공자 이름을 안다."""

from .base import KINDS, Provider, ProviderRequest, ProviderResult, all_names, available_names, describe, get, register
from .code import CodeProvider
from .local import LocalProvider
from .pixellab import PixelLabProvider

register(CodeProvider())
register(LocalProvider())
register(PixelLabProvider())

DEFAULT = "code"

__all__ = [
   "KINDS",
   "Provider",
   "ProviderRequest",
   "ProviderResult",
   "DEFAULT",
   "all_names",
   "available_names",
   "describe",
   "get",
   "register",
]
