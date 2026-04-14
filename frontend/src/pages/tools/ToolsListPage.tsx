import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Wrench } from 'lucide-react';
import { Badge, Button, Card, EmptyState, PageHeader, Spinner } from '@/components/ui';
import { ToolStatusBadge } from '@/components/tools/ToolStatusBadge';
import { useDiscoverTools, useLocalTools } from '@/hooks/useLocalTools';
import { findMarketplaceTool, useMarketplaceTools } from '@/hooks/useMarketplaceTools';
import { PublishStatus } from '@/types/marketplace';

type ActiveFilter = 'all' | PublishStatus;

function validationBadgeVariant(status: string): 'success' | 'warning' | 'error' | 'neutral' {
  const normalized = status.toLowerCase();
  if (normalized === 'passed' || normalized === 'ok') return 'success';
  if (normalized === 'failed' || normalized === 'error') return 'error';
  if (normalized === 'pending') return 'warning';
  return 'neutral';
}

function formatValidationStatus(status: string) {
  return status.replace(/_/g, ' ');
}

function formatPrice(price?: number) {
  if (typeof price !== 'number') return 'No pricing';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: price < 1 ? 3 : 2,
    maximumFractionDigits: price < 1 ? 3 : 2,
  }).format(price);
}

function RegistrationBanner() {
  return (
    <Card className="border-amber-200 bg-amber-50">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold text-amber-900">
            Complete node registration to manage marketplace tools
          </h2>
          <p className="mt-1 text-sm text-amber-800">
            Marketplace data is unavailable until seller registration is finished.
          </p>
        </div>
        <Link
          to="/setup/review"
          className="inline-flex items-center justify-center rounded-brand border border-amber-300 px-4 py-2 text-sm font-medium text-amber-900 transition-colors hover:bg-amber-100"
        >
          Open setup
        </Link>
      </div>
    </Card>
  );
}

export function ToolsListPage() {
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>('all');
  const localToolsQuery = useLocalTools();
  const marketplaceToolsQuery = useMarketplaceTools();
  const discoverTools = useDiscoverTools();

  const items = useMemo(() => {
    const tools = localToolsQuery.data?.tools ?? [];
    const marketplaceTools = marketplaceToolsQuery.data?.tools ?? [];

    return tools.map((tool) => {
      const marketplace = findMarketplaceTool(tool, marketplaceTools);
      return {
        ...tool,
        publish_status: marketplace?.status ?? 'not_published',
        price_usd: marketplace?.price_usd,
      };
    });
  }, [localToolsQuery.data?.tools, marketplaceToolsQuery.data?.tools]);

  const filteredItems = useMemo(() => {
    if (activeFilter === 'all') return items;
    return items.filter((item) => item.publish_status === activeFilter);
  }, [activeFilter, items]);

  const isLoading = localToolsQuery.isLoading || marketplaceToolsQuery.isLoading;
  const error =
    localToolsQuery.error instanceof Error
      ? localToolsQuery.error.message
      : marketplaceToolsQuery.error instanceof Error
        ? marketplaceToolsQuery.error.message
        : null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tools"
        description="Manage your local tools and track marketplace publish status."
        actions={
          <Button
            variant="secondary"
            loading={discoverTools.isPending}
            onClick={() => discoverTools.mutate()}
          >
            Discover Tools
          </Button>
        }
      />

      {marketplaceToolsQuery.data?.setupIncomplete && <RegistrationBanner />}

      <div className="flex flex-wrap gap-2">
        {(['all', 'not_published', 'draft', 'live'] as const).map((filter) => (
          <button
            key={filter}
            type="button"
            className={`rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
              activeFilter === filter
                ? 'bg-brand-indigo text-white'
                : 'bg-white text-brand-text-secondary hover:bg-brand-surface'
            }`}
            onClick={() => setActiveFilter(filter)}
          >
            {filter === 'all' ? 'All' : filter.replace('_', ' ')}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex min-h-[240px] items-center justify-center">
          <Spinner size="lg" />
        </div>
      ) : error ? (
        <Card>
          <p role="alert" className="text-sm text-brand-error">
            {error}
          </p>
        </Card>
      ) : filteredItems.length === 0 ? (
        <EmptyState
          icon={<Wrench size={40} />}
          title="No tools found"
          description="Run discovery to load local tools from your upstream provider."
          action={
            <Button
              variant="primary"
              loading={discoverTools.isPending}
              onClick={() => discoverTools.mutate()}
            >
              Discover Tools
            </Button>
          }
        />
      ) : (
        <div className="space-y-4">
          {filteredItems.map((tool) => (
            <Link key={tool.tool_id} to={`/tools/${tool.tool_id}`} className="block">
              <Card className="transition-colors hover:border-brand-indigo/40 hover:shadow-md">
                <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-lg font-semibold text-brand-text">{tool.name}</h2>
                      <Badge variant="neutral">v{tool.version}</Badge>
                      <Badge variant={validationBadgeVariant(tool.validation_status)}>
                        {formatValidationStatus(tool.validation_status)}
                      </Badge>
                    </div>
                    <p className="text-sm text-brand-text-secondary">
                      {tool.description || 'No description available.'}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 md:justify-end">
                    <ToolStatusBadge status={tool.publish_status} />
                    <Badge variant="info">{formatPrice(tool.price_usd)}</Badge>
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
