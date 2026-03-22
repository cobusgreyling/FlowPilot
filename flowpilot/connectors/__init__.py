"""FlowPilot connectors — integrations with external services."""

from flowpilot.connectors.base import BaseConnector
from flowpilot.connectors.slack import SlackConnector
from flowpilot.connectors.github_connector import GitHubConnector
from flowpilot.connectors.email_connector import EmailConnector
from flowpilot.connectors.http_connector import HttpConnector
from flowpilot.connectors.transform import TransformConnector
from flowpilot.connectors.ai_connector import AIConnector
from flowpilot.connectors.notification import NotificationConnector
from flowpilot.connectors.database import DatabaseConnector
from flowpilot.connectors.google_workspace import GoogleWorkspaceConnector
from flowpilot.connectors.jira_connector import JiraConnector
from flowpilot.connectors.aws_connector import AWSConnector
from flowpilot.connectors.stripe_connector import StripeConnector
from flowpilot.connectors.twilio_connector import TwilioConnector
from flowpilot.connectors.postgres_connector import PostgresConnector
