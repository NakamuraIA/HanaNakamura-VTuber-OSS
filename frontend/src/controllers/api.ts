import { ChatApi } from "../api/chat";
import { SystemApi } from "../api/system";
import { ConfigApi } from "../api/config";
import { AgentJobsApi } from "../api/agentJobs";
import { McpApi } from "../api/mcp";
import { TerminalAgentApi } from "../api/terminalAgent";
import { RemindersApi } from "../api/reminders";

export const ApiController = {
  ...ChatApi,
  ...SystemApi,
  ...ConfigApi,
  ...AgentJobsApi,
  ...McpApi,
  ...TerminalAgentApi,
  ...RemindersApi,
};
