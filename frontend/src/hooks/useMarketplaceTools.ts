import { useQuery } from '@tanstack/react-query';
import { ApiError, api } from '@/lib/api';
import { MarketplaceTool, PublishStatus } from '@/types/marketplace';
import { ToolSummary } from '@/hooks/useLocalTools';

interface MarketplaceToolsResult {
  tools: MarketplaceTool[];
  setupIncomplete: boolean;
}

function normalizeStatus(value: unknown): PublishStatus {
  const normalized = String(value ?? '').trim().toLowerCase();
  if (normalized === 'draft') return 'draft';
  if (normalized === 'live' || normalized === 'published' || normalized === 'active') return 'live';
  return 'not_published';
}

function normalizePrice(rawTool: Record<string, unknown>): number | undefined {
  const direct = rawTool.price_usd;
  if (typeof direct === 'number' && Number.isFinite(direct)) return direct;

  const pricing = rawTool.pricing_formula;
  if (pricing && typeof pricing === 'object' && pricing !== null) {
    const priceCents = (pricing as Record<string, unknown>).price_cents;
    if (typeof priceCents === 'number' && Number.isFinite(priceCents)) {
      return priceCents / 100;
    }
  }

  return undefined;
}

function normalizeTool(rawTool: Record<string, unknown>): MarketplaceTool {
  const tags = Array.isArray(rawTool.tags)
    ? rawTool.tags.filter((tag): tag is string => typeof tag === 'string')
    : undefined;

  return {
    tool_id: String(
      rawTool.tool_id ??
        rawTool.id ??
        rawTool.tool_name ??
        rawTool.name ??
        '',
    ),
    tool_name:
      typeof rawTool.tool_name === 'string'
        ? rawTool.tool_name
        : typeof rawTool.name === 'string'
          ? rawTool.name
          : undefined,
    listing_id: typeof rawTool.listing_id === 'string' ? rawTool.listing_id : undefined,
    status: normalizeStatus(rawTool.status),
    title: typeof rawTool.title === 'string' ? rawTool.title : undefined,
    description: typeof rawTool.description === 'string' ? rawTool.description : undefined,
    category: typeof rawTool.category === 'string' ? rawTool.category : undefined,
    tags,
    price_usd: normalizePrice(rawTool),
    free_tier_calls:
      typeof rawTool.free_tier_calls === 'number' ? rawTool.free_tier_calls : undefined,
    rate_limit_per_minute:
      typeof rawTool.rate_limit_per_minute === 'number'
        ? rawTool.rate_limit_per_minute
        : undefined,
    published_at: typeof rawTool.published_at === 'string' ? rawTool.published_at : undefined,
    updated_at: typeof rawTool.updated_at === 'string' ? rawTool.updated_at : undefined,
  };
}

function normalizeMarketplacePayload(payload: unknown): MarketplaceTool[] {
  const items = Array.isArray(payload)
    ? payload
    : payload && typeof payload === 'object' && Array.isArray((payload as { tools?: unknown[] }).tools)
      ? (payload as { tools: unknown[] }).tools
      : [];

  return items
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map(normalizeTool);
}

export function findMarketplaceTool(
  localTool: Pick<ToolSummary, 'tool_id' | 'name'>,
  tools: MarketplaceTool[],
) {
  return (
    tools.find((tool) => tool.tool_id === localTool.tool_id) ??
    tools.find((tool) => tool.tool_name === localTool.name) ??
    tools.find((tool) => tool.tool_id === localTool.name) ??
    null
  );
}

export function useMarketplaceTools() {
  return useQuery<MarketplaceToolsResult>({
    queryKey: ['marketplace-tools'],
    queryFn: async () => {
      try {
        const payload = await api.get<unknown>('/marketplace/tools');
        return {
          tools: normalizeMarketplacePayload(payload),
          setupIncomplete: false,
        };
      } catch (error) {
        if (error instanceof ApiError && error.status === 412 && error.code === 'setup_incomplete') {
          return {
            tools: [],
            setupIncomplete: true,
          };
        }

        throw error;
      }
    },
  });
}

