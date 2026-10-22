// Shapes returned by the Lead Intelligence API.

export type ProspectStatus =
  | 'NEW' | 'REVIEW' | 'APPROVED' | 'REJECTED' | 'CONTACTED' | 'REPLIED'
  | 'MEETING' | 'PROPOSAL' | 'WON' | 'LOST' | 'DO_NOT_CONTACT';
export const STATUSES: ProspectStatus[] = ['NEW', 'REVIEW', 'APPROVED', 'REJECTED', 'CONTACTED', 'REPLIED', 'MEETING', 'PROPOSAL', 'WON', 'LOST', 'DO_NOT_CONTACT'];
export const statusLabel = (s: string) => s.replace(/_/g, ' ');

export type Priority = 'HIGH' | 'MEDIUM' | 'LOW';
export type EmailStatus = 'VERIFIED' | 'LIKELY' | 'UNKNOWN' | 'INVALID' | 'RISKY' | 'UNVERIFIED';
export type Provenance = 'DISCOVERED' | 'INFERRED' | 'ENRICHED' | 'VERIFIED' | 'USER_PROVIDED';

export interface Paged<T> { items: T[]; total: number; page: number; page_size: number }

export interface Location { id?: number; address?: string | null; city: string | null; state: string | null; postcode?: string | null; country?: string | null; is_primary?: boolean }

export interface Source {
  id: number; field: string; value: string | null; provenance: Provenance; source_type: string; provider: string | null;
  source_url: string | null; evidence: string | null; confidence: number | null; retrieved_at: string | null;
}

export interface CompanySummary {
  id: number; legal_name: string; display_name: string; website: string | null; domain: string | null;
  domain_confidence: number | null; domain_status: string; industry: string | null; description: string | null;
  employee_estimate: number | null; employee_estimate_source: string | null; phone: string | null; general_email: string | null;
  deal_value: number | null; is_demo: boolean; location: Location | null; contact_count: number | null;
  last_crawled_at: string | null; last_enriched_at: string | null; created_at: string; updated_at: string;
}

export interface Opportunity {
  id: number; program: string; match_score: number; reason: string; target_department?: string | null;
  recommended_decision_maker: string | null; evidence: { source_url: string; quote: string }[]; method: string; computed_at?: string | null;
}

export interface Signal {
  id: number; signal_type: string; title: string; description: string | null; evidence: string | null; source_url: string | null;
  source_date: string | null; provenance: Provenance; confidence: number | null; discovered_at: string | null;
}

export interface Activity { id: number; type: string; text: string; meta: Record<string, unknown>; contact_id: number | null; company_id: number | null; user: string | null; created_at: string }
export interface Note { id: number; body: string; contact_id: number | null; company_id: number | null; user: string | null; user_id: number | null; created_at: string; updated_at: string }

export interface CompanyDetail extends CompanySummary {
  locations: Location[]; sources: Source[];
  contacts: { id: number; full_name: string; original_title: string | null; normalized_title: string | null; department: string | null; seniority: string | null; status: ProspectStatus; lead_score: number | null; priority: Priority | null }[];
  training_opportunities: Opportunity[]; signals: Signal[]; activities: Activity[]; notes: Note[];
  crawl_history: { id: number; domain: string; status: string; pages_fetched: number; pages_skipped: number; robots_allowed: boolean | null; error: string | null; started_at: string | null; finished_at: string | null }[];
  invoices: { invoice_number: string; amount: number; contact_id: number | null; created_at: string }[];
  possible_duplicates: { other_id?: number; id?: number; legal_name?: string; similarity: number; reasons?: string[] }[];
  suppressed: string[]; can_edit: boolean;
}

export interface Email {
  id: number; email: string; email_type: string; discovery_method: string; provenance: Provenance; source: string | null;
  source_url: string | null; confidence: number | null; verification_status: EmailStatus; verification_provider: string | null;
  verified_at: string | null; is_primary: boolean; created_at: string;
}
export interface Profile { id: number; platform: string; url: string; source_type: string; provider: string | null; source_url: string | null; confidence: number | null; retrieved_at: string | null }
export interface ScoreFactor { factor: string; points: number; max_points: number; met: boolean; explanation: string }

export interface ContactDetail {
  id: number; full_name: string; first_name: string | null; last_name: string | null; original_title: string | null;
  normalized_title: string | null; department: string | null; seniority: string | null; phone: string | null;
  status: ProspectStatus; status_changed_at: string | null; last_contacted_at: string | null; follow_up_at: string | null;
  created_at: string; updated_at: string;
  company: { id: number; legal_name: string; display_name: string; industry: string | null; domain: string | null; website: string | null; deal_value: number | null; location: Location | null };
  emails: Email[]; profiles: Profile[]; sources: Source[];
  lead_score: { score: number; priority: Priority; breakdown: ScoreFactor[]; computed_at: string } | null;
  contact_confidence: { score: number; breakdown: ScoreFactor[]; computed_at: string } | null;
  training_opportunities: Opportunity[]; activities: Activity[]; notes: Note[];
  invoice: { invoice_number: string; amount: number; created_at: string } | null;
  suppressed: string[]; can_edit: boolean;
  invoice_error?: string | null; possible_duplicates?: { id: number; full_name: string; similarity: number }[];
}

export interface Prospect {
  id: number; full_name: string; original_title: string | null; normalized_title: string | null; department: string | null;
  seniority: string | null; status: ProspectStatus; status_changed_at: string | null; last_contacted_at: string | null;
  follow_up_at: string | null; created_at: string;
  company: { id: number; legal_name: string; display_name: string; industry: string | null; employee_estimate: number | null; domain: string | null; deal_value: number | null };
  location: { city: string | null; state: string | null } | null;
  email: string | null; email_status: EmailStatus | null; email_provenance: Provenance | null; profile_url: string | null;
  lead_score: number | null; priority: Priority | null; contact_confidence: number | null;
  training_program: string | null; match_score: number | null; source_count: number; suppressed: boolean;
}

export interface Meta {
  statuses: ProspectStatus[]; departments: string[]; seniorities: string[]; email_statuses: EmailStatus[]; priorities: Priority[];
  provenances: Provenance[]; source_types: string[]; industries: string[]; states: string[];
  programs: { id: number; code: string; name: string; enabled: boolean }[];
}
