export type PublishStatus = 'not_published' | 'draft' | 'live';

export interface MarketplaceTool {
  tool_id: string;
  tool_name?: string;
  listing_id?: string;
  status: PublishStatus;
  title?: string;
  description?: string;
  category?: string;
  tags?: string[];
  price_usd?: number;
  free_tier_calls?: number;
  rate_limit_per_minute?: number;
  published_at?: string;
  updated_at?: string;
}

