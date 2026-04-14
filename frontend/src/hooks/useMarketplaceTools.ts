import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, api } from '@/lib/api';
import {
  MarketplaceListing,
  MarketplaceTool,
  PricingFormula,
  PublishStatus,
  PublishToolPayload,
  ToolUpdateRequest,
} from '@/types/marketplace';
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

function normalizePricingFormula(rawTool: Record<string, unknown>): PricingFormula | undefined {
  const pricing = rawTool.pricing_formula;
  if (!pricing || typeof pricing !== 'object') return undefined;

  const rawModel = (pricing as Record<string, unknown>).model;
  const rawPrice = (pricing as Record<string, unknown>).price_cents;

  if (
    (rawModel === 'per_call' || rawModel === 'per_minute' || rawModel === 'flat_monthly') &&
    typeof rawPrice === 'number' &&
    Number.isFinite(rawPrice)
  ) {
    return {
      model: rawModel,
      price_cents: rawPrice,
    };
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
    nl_description:
      typeof rawTool.nl_description === 'string' ? rawTool.nl_description : undefined,
    title: typeof rawTool.title === 'string' ? rawTool.title : undefined,
    description: typeof rawTool.description === 'string' ? rawTool.description : undefined,
    category: typeof rawTool.category === 'string' ? rawTool.category : undefined,
    tags,
    price_usd: normalizePrice(rawTool),
    pricing_formula: normalizePricingFormula(rawTool),
    free_tier_calls:
      typeof rawTool.free_tier_calls === 'number' ? rawTool.free_tier_calls : undefined,
    rate_limit_per_minute:
      typeof rawTool.rate_limit_per_minute === 'number'
        ? rawTool.rate_limit_per_minute
        : undefined,
    input_schema:
      rawTool.input_schema && typeof rawTool.input_schema === 'object'
        ? (rawTool.input_schema as Record<string, unknown>)
        : undefined,
    output_schema:
      rawTool.output_schema && typeof rawTool.output_schema === 'object'
        ? (rawTool.output_schema as Record<string, unknown>)
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

function normalizeListing(raw: Record<string, unknown>): MarketplaceListing {
  return {
    listing_id: String(raw.listing_id ?? raw.id ?? ''),
    title: typeof raw.title === 'string' ? raw.title : undefined,
    description: typeof raw.description === 'string' ? raw.description : undefined,
    status: typeof raw.status === 'string' ? raw.status : undefined,
  };
}

function normalizeListingsPayload(payload: unknown): MarketplaceListing[] {
  const items = Array.isArray(payload)
    ? payload
    : payload && typeof payload === 'object' && Array.isArray((payload as { listings?: unknown[] }).listings)
      ? (payload as { listings: unknown[] }).listings
      : [];
  return items
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map(normalizeListing)
    .filter((item) => item.listing_id);
}

interface MarketplaceListingsResult {
  listings: MarketplaceListing[];
  setupIncomplete: boolean;
}

export function useMarketplaceListings() {
  return useQuery<MarketplaceListingsResult>({
    queryKey: ['marketplace-listings'],
    queryFn: async () => {
      try {
        const payload = await api.get<unknown>('/marketplace/listings');
        return { listings: normalizeListingsPayload(payload), setupIncomplete: false };
      } catch (error) {
        if (
          error instanceof ApiError &&
          error.status === 412 &&
          error.code === 'setup_incomplete'
        ) {
          return { listings: [], setupIncomplete: true };
        }
        throw error;
      }
    },
  });
}

export function usePublishTool() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: PublishToolPayload) =>
      api.post<Record<string, unknown>>('/marketplace/tools/publish', payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['marketplace-tools'] });
    },
  });
}

export function useUpdateTool(toolId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ToolUpdateRequest) =>
      api.put<Record<string, unknown>>(`/marketplace/tools/${toolId}`, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['marketplace-tools'] });
    },
  });
}

export function useUnpublishTool(toolId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.delete<Record<string, unknown>>(`/marketplace/tools/${toolId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['marketplace-tools'] });
    },
  });
}
