// Empty = same origin: Next.js forwards /api to the backend (see next.config.ts).
export const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

export type Role = "patient" | "hospital" | "insurer" | "finance" | "admin";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  created_at: string;
}

export interface ShapItem {
  feature: string;
  value?: string | number;
  shap_usd: number;
  shap_inr: number;
}

export interface CostEstimate {
  id: number;
  inputs: Record<string, string | number>;
  predicted_usd: number;
  predicted_inr: number;
  shap: ShapItem[];
  created_at: string;
}

export interface Profile {
  age: number;
  sex: "male" | "female";
  bmi: number;
  children: number;
  smoker: "yes" | "no";
  region: string;
  marital_status: string;
  employment_status: string;
  monthly_income: number;
  existing_monthly_debt: number;
  has_credit_card: boolean;
}

export interface Policy {
  id: number;
  policy_number: string;
  patient_id: number;
  insurer_id: number;
  deductible: number;
  co_insurance_pct: number;
  copay_flat: number;
  room_rent_cap: number | null;
  sum_insured: number | null;
  active: boolean;
  created_at: string;
  patient_name?: string;
  insurer_name?: string;
}

export interface BillItem {
  id: number;
  description: string;
  category: string;
  amount: number;
  quantity: number;
  is_covered: boolean;
  fair_price: number | null;
  overcharge_pct: number | null;
  ml_anomaly: boolean;
  severity: "normal" | "review" | "high_risk";
  duplicate_of: string | null;
  duplicate_similarity: number | null;
}

export interface BillSummary {
  id: number;
  patient_id: number;
  hospital_id: number | null;
  source: string;
  hospital_name: string | null;
  bill_number: string | null;
  total_billed: number;
  insurance_pays: number;
  patient_out_of_pocket: number;
  flagged_amount: number;
  duplicate_count: number;
  high_risk_count: number;
  total_mismatch: boolean;
  payment_status: "unpaid" | "paid" | "on_emi";
  created_at: string;
  patient_name?: string;
  claim_status?: string | null;
}

export interface Recommendation {
  option: string;
  suitability_score: number;
  reasoning: string;
  details: Record<string, unknown>;
}

export interface EMIPlan {
  principal: number;
  annual_interest_rate: number;
  tenure_months: number;
  monthly_emi: number;
  total_payment: number;
  total_interest: number;
  schedule: { month: number; emi: number; principal_component: number; interest_component: number; remaining_balance: number }[];
}

export interface BillDetail extends BillSummary {
  admission_date: string | null;
  discharge_date: string | null;
  stated_total: number | null;
  city_tier: string;
  hospital_type: string;
  raw_text: string | null;
  cost_breakdown: Record<string, number | unknown>;
  emi: { plan?: EMIPlan; tenure_comparison?: { tenure_months: number; monthly_emi: number; total_payment: number; total_interest: number }[] };
  recommendations: Recommendation[];
  items: BillItem[];
  policy_id: number | null;
  claim_id: number | null;
  payment: null | { plan: string; principal: number; annual_rate: number; tenure_months: number; monthly_emi: number; total_payment: number; created_at: string };
}

export interface Factor {
  feature: string;
  impact: number;
  direction: string;
}

export interface Advice {
  decision: "approve" | "approve_reduced" | "verify" | "investigate" | "reject";
  label: string;
  summary: string;
  claimed_amount: number;
  recommended_amount: number;
  saving: number;
  bill_deductions: { description: string; billed: number; deducted: number; reason: string }[];
  total_deducted_from_bill: number;
  review_items: string[];
  checks: { name: string; ok: boolean; detail: string }[];
  method: string;
}

export interface Claim {
  id: number;
  claim_number: string;
  bill_id: number | null;
  patient_id: number;
  hospital_id: number | null;
  insurer_id: number;
  claim_amount: number;
  claim_type: string;
  provider_specialty: string;
  submission_method: string;
  provider_location: string;
  fraud_probability: number;
  anomaly_score: number;
  hybrid_risk_score: number;
  fraud_prediction: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  recommendation: string;
  top_factors: Factor[];
  model_inputs: Record<string, string | number>;
  status: "submitted" | "approved" | "rejected" | "settled";
  approved_amount: number | null;
  decision_note: string | null;
  submitted_at: string;
  decided_at: string | null;
  patient_name?: string;
  hospital_name?: string | null;
  insurer_name?: string;
  advice?: Advice | null;
}

export interface Options {
  regions: string[];
  specialties: string[];
  claim_types: string[];
  submission_methods: string[];
  marital_statuses: string[];
  employment_statuses: string[];
  city_tiers: string[];
  hospital_types: string[];
  categories: string[];
  usd_to_inr: number;
}

export interface Person {
  id: number;
  full_name: string;
  email: string;
}

export interface Hospital {
  id: number;
  name: string;
  city: string;
  city_tier: string;
  hospital_type: string;
}

// ------------------------------------------------------------ session

const TOKEN_KEY = "hb_token";
const USER_KEY = "hb_user";

export function saveSession(token: string, user: User) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    /* storage unavailable: session lasts for this page only */
  }
  memory = { token, user };
}

let memory: { token: string; user: User } | null = null;

export function getSession(): { token: string; user: User } | null {
  if (memory) return memory;
  try {
    const token = localStorage.getItem(TOKEN_KEY);
    const user = localStorage.getItem(USER_KEY);
    if (token && user) memory = { token, user: JSON.parse(user) };
  } catch {
    return null;
  }
  return memory;
}

export function clearSession() {
  memory = null;
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  } catch {
    /* ignore */
  }
}

export const HOME: Record<Role, string> = {
  patient: "/patient",
  hospital: "/hospital",
  insurer: "/insurance",
  finance: "/finance",
  admin: "/admin",
};

// ------------------------------------------------------------ fetch

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d: { loc?: (string | number)[]; msg?: string }) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`)
        .join("; ");
    }
  }
  return `Request failed (${status}).`;
}

export async function api<T>(path: string, options: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const session = getSession();
  const headers: Record<string, string> = {};
  if (session) headers.Authorization = `Bearer ${session.token}`;
  let body: BodyInit | undefined;
  if (options.form) body = options.form;
  else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { method: options.method || (body ? "POST" : "GET"), headers, body });
  } catch {
    throw new ApiError(0, "Cannot reach the HealthBridge API. Is the backend running?");
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    if (res.status === 401 && session) {
      clearSession();
      if (typeof window !== "undefined") window.location.href = "/login";
    }
    throw new ApiError(res.status, errorMessage(data, res.status));
  }
  return data as T;
}
