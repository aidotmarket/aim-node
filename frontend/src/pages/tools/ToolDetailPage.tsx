import { useMemo } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Badge, Button, Card, PageHeader, Spinner } from '@/components/ui';
import { ToolSchemaPanel } from '@/components/tools/ToolSchemaPanel';
import { ToolStatusBadge } from '@/components/tools/ToolStatusBadge';
import { useToolDetail, useValidateTool } from '@/hooks/useLocalTools';
import { findMarketplaceTool, useMarketplaceTools } from '@/hooks/useMarketplaceTools';

function validationBadgeVariant(status: string): 'success' | 'warning' | 'error' | 'neutral' {
  const normalized = status.toLowerCase();
  if (normalized === 'passed' || normalized === 'ok') return 'success';
  if (normalized === 'failed' || normalized === 'error') return 'error';
  if (normalized === 'pending') return 'warning';
  return 'neutral';
}

function formatDateLabel(value: string | null) {
  if (!value) return 'Not validated yet';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatPrice(price?: number) {
  if (typeof price !== 'number') return 'No pricing configured';
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
            Marketplace status is unavailable until the seller setup flow is completed.
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

export function ToolDetailPage() {
  const navigate = useNavigate();
  const { toolId } = useParams();
  const [searchParams] = useSearchParams();
  const toolDetailQuery = useToolDetail(toolId);
  const marketplaceToolsQuery = useMarketplaceTools();
  const validateTool = useValidateTool(toolId);

  const marketplace = useMemo(() => {
    if (!toolDetailQuery.data) return null;
    return findMarketplaceTool(toolDetailQuery.data, marketplaceToolsQuery.data?.tools ?? []);
  }, [marketplaceToolsQuery.data?.tools, toolDetailQuery.data]);

  const isLoading = toolDetailQuery.isLoading || marketplaceToolsQuery.isLoading;
  const error =
    toolDetailQuery.error instanceof Error
      ? toolDetailQuery.error.message
      : marketplaceToolsQuery.error instanceof Error
        ? marketplaceToolsQuery.error.message
        : null;

  if (isLoading) {
    return (
      <div className="flex min-h-[240px] items-center justify-center">
        <Spinner size="lg" />
      </div>
    );
  }

  if (error || !toolDetailQuery.data) {
    return (
      <Card>
        <p role="alert" className="text-sm text-brand-error">
          {error ?? 'Tool not found'}
        </p>
      </Card>
    );
  }

  const tool = toolDetailQuery.data;
  const publishAction = searchParams.get('action');

  return (
    <div className="space-y-6">
      <PageHeader
        title={tool.name}
        description="Inspect schemas, validation status, and marketplace publish state."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              loading={validateTool.isPending}
              onClick={() => validateTool.mutate()}
            >
              Validate
            </Button>
            <Button
              variant="primary"
              onClick={() => navigate(`/tools/${tool.tool_id}?action=publish`)}
            >
              Publish
            </Button>
            <Button
              variant="secondary"
              onClick={() => navigate(`/tools/${tool.tool_id}?action=update`)}
            >
              Update
            </Button>
            <Button
              variant="ghost"
              onClick={() => navigate(`/tools/${tool.tool_id}?action=unpublish`)}
            >
              Unpublish
            </Button>
          </div>
        }
      />

      {marketplaceToolsQuery.data?.setupIncomplete && <RegistrationBanner />}

      {publishAction && (
        <Card className="border-indigo-200 bg-indigo-50">
          <p className="text-sm text-brand-indigo">
            {publishAction === 'publish'
              ? 'Publish flow ships in Slice C. This action is linked and ready for follow-up work.'
              : `${publishAction.charAt(0).toUpperCase()}${publishAction.slice(1)} flow ships in Slice C.`}
          </p>
        </Card>
      )}

      <Card>
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="neutral">v{tool.version}</Badge>
              <Badge variant={validationBadgeVariant(tool.validation_status)}>
                {tool.validation_status.replace(/_/g, ' ')}
              </Badge>
              <ToolStatusBadge status={marketplace?.status ?? 'not_published'} />
            </div>
            <p className="text-sm text-brand-text-secondary">
              {tool.description || 'No description available.'}
            </p>
          </div>
          <div className="rounded-brand bg-brand-surface px-4 py-3 text-sm">
            <p className="font-medium text-brand-text">Marketplace pricing</p>
            <p className="mt-1 text-brand-text-secondary">{formatPrice(marketplace?.price_usd)}</p>
          </div>
        </div>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <ToolSchemaPanel title="Input Schema" schema={tool.input_schema} />
        <ToolSchemaPanel title="Output Schema" schema={tool.output_schema} />
      </div>

      <Card>
        <div className="space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-brand-text">Validation</h2>
            <p className="mt-1 text-sm text-brand-text-secondary">
              Review the latest local validation status for this tool.
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <p className="text-xs uppercase tracking-wide text-brand-text-secondary">Status</p>
              <p className="mt-1 text-sm font-medium text-brand-text">{tool.validation_status}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-brand-text-secondary">
                Last validated
              </p>
              <p className="mt-1 text-sm font-medium text-brand-text">
                {formatDateLabel(tool.last_validated_at)}
              </p>
            </div>
          </div>
        </div>
      </Card>

      <Card>
        <div className="space-y-3">
          <div>
            <h2 className="text-sm font-semibold text-brand-text">Marketplace</h2>
            <p className="mt-1 text-sm text-brand-text-secondary">
              Current marketplace state for this tool.
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <p className="text-xs uppercase tracking-wide text-brand-text-secondary">Publish status</p>
              <div className="mt-2">
                <ToolStatusBadge status={marketplace?.status ?? 'not_published'} />
              </div>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-brand-text-secondary">Listing</p>
              <p className="mt-1 text-sm font-medium text-brand-text">
                {marketplace?.listing_id ?? 'Not listed'}
              </p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-brand-text-secondary">Pricing</p>
              <p className="mt-1 text-sm font-medium text-brand-text">{formatPrice(marketplace?.price_usd)}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-brand-text-secondary">Updated</p>
              <p className="mt-1 text-sm font-medium text-brand-text">
                {formatDateLabel(marketplace?.updated_at ?? null)}
              </p>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
