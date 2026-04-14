export type PublishStatus = 'not_published' | 'draft' | 'live';

export type PricingModel = 'per_call' | 'per_minute' | 'flat_monthly';

export interface PricingFormula {
  model: PricingModel;
  price_cents: number;
}

export interface MarketplaceTool {
  tool_id: string;
  tool_name?: string;
  listing_id?: string;
  status: PublishStatus;
  nl_description?: string;
  title?: string;
  description?: string;
  category?: string;
  tags?: string[];
  price_usd?: number;
  pricing_formula?: PricingFormula;
  free_tier_calls?: number;
  rate_limit_per_minute?: number;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  published_at?: string;
  updated_at?: string;
}

export interface MarketplaceListing {
  listing_id: string;
  title?: string;
  description?: string;
  status?: string;
}

export interface PublishToolPayload {
  listing_id: string;
  tool_name: string;
  version: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  nl_description: string;
  pricing_formula: PricingFormula;
  execution_mode: 'sync';
  task_taxonomy_tags: string[];
  sample_io_pairs: Array<Record<string, unknown>>;
  intended_use?: string;
  limitations_and_known_failures?: string;
}

export interface ToolUpdateRequest {
  nl_description?: string;
  pricing_formula?: PricingFormula;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
}
