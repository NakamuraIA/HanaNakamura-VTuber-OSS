import { AgentJob, AgentJobsResponse } from "../models/types";
import { backendFetch, readJson } from "./core";

const EMPTY_AGENT_JOBS: AgentJobsResponse = { ok: false, jobs: [], active: [] };

export const AgentJobsApi = {
  /**
   * Lists Omni background jobs retained by the backend.
   */
  getAgentJobs: async (): Promise<AgentJobsResponse> => {
    return readJson("/api/agent-jobs", EMPTY_AGENT_JOBS);
  },

  /**
   * Requests cancellation for one running background job.
   */
  cancelAgentJob: async (jobId: string, reason = "control_panel"): Promise<{ ok: boolean; job?: AgentJob; error?: string }> => {
    try {
      const res = await backendFetch(`/api/agent-jobs/${encodeURIComponent(jobId)}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      return await res.json();
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : "backend_unavailable" };
    }
  },

  /**
   * Requests cancellation for active Omni jobs, optionally scoped by agent.
   */
  cancelActiveAgentJobs: async (agent?: "omni", reason = "control_panel") => {
    try {
      const res = await backendFetch("/api/agent-jobs/cancel-active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent: agent || "", reason }),
      });
      return await res.json();
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : "backend_unavailable" };
    }
  },
};
