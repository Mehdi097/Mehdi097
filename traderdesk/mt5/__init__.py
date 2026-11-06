"""Connecteurs MetaTrader 5 : simulation, passerelle REST (adresse + clé API), terminal local."""

from .connector import (  # noqa: F401
    MT5Error, SimulationConnector, RestConnector, LocalConnector, ConnectorManager,
)
