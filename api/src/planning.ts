import { ApiError } from './errors.js';
export interface PlanningInput {
  reference: any; matrix: any; day: any; previous_plan: any; event: any; calendar?: Record<string,any>;
}
export type Planner = (input: PlanningInput, timeoutMs: number) => Promise<any>;
// Explicit integration boundary. No fabricated successful plan when the planner is unavailable.
export const httpPlanner: Planner = async (input, timeoutMs) => {
  const url = process.env.PLANNER_URL;
  if (!url) throw new ApiError(503, 'PLANNER_UNAVAILABLE', 'PLANNER_URL is not configured');
  try {
    const response = await fetch(url, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({...input,time_limit_sec:Math.max(0.1, timeoutMs/1000-1)}), signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) throw new Error(`Planner returned ${response.status}`);
    return await response.json();
  } catch {
    throw new ApiError(503, 'PLANNER_UNAVAILABLE', 'Planner failed or timed out');
  }
};


