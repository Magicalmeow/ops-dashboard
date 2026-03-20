from src.collectors.base import BaseCollector
from src.collectors.weather import WeatherCollector
from src.collectors.market_maker import MarketMakerCollector
from src.collectors.decoded import DecodedCollector
from src.collectors.momentum import MomentumCollector
from src.collectors.git_collector import GitCollector


COLLECTOR_MAP = {
    "trading_weather": WeatherCollector,
    "trading_mm": MarketMakerCollector,
    "trading_decoded": DecodedCollector,
    "trading_momentum": MomentumCollector,
    "git": GitCollector,
}


def create_collector(project_config: dict) -> BaseCollector:
    """Factory: create a collector from a project config dict."""
    collector_type = project_config["collector_type"]
    cls = COLLECTOR_MAP[collector_type]
    return cls(project_config)
