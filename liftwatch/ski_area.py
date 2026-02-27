from enum import IntEnum

class SkiArea(IntEnum):
    ANNUPURI = 393
    NISEKO_VILLAGE = 394
    GRAND_HIRAFU = 390
    HANAZONO = 379

    @property
    def label(self) -> str:
        return {
            SkiArea.ANNUPURI: "Annupuri",
            SkiArea.NISEKO_VILLAGE: "Niseko Village",
            SkiArea.GRAND_HIRAFU: "Grand Hirafu",
            SkiArea.HANAZONO: "Hanazono",
        }[self]