import { ChatApi } from "../api/chat";
import { SystemApi } from "../api/system";
import { ConfigApi } from "../api/config";
import { AgentJobsApi } from "../api/agentJobs";
import { McpApi } from "../api/mcp";
import { MemoryApi } from "../api/memory";
import { TerminalAgentApi } from "../api/terminalAgent";

export const ApiController = {
  ...ChatApi,
  ...SystemApi,
  ...ConfigApi,
  ...AgentJobsApi,
  ...McpApi,
  ...MemoryApi,
  ...TerminalAgentApi,
};
