"""FlowPilot connectors — integrations with external services."""

from flowpilot.connectors.base import BaseConnector
from flowpilot.connectors.slack import SlackConnector
from flowpilot.connectors.github_connector import GitHubConnector
from flowpilot.connectors.email_connector import EmailConnector
from flowpilot.connectors.http_connector import HttpConnector
from flowpilot.connectors.transform import TransformConnector
from flowpilot.connectors.ai_connector import AIConnector
