import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Button, Card, Field, Input, PageHeader, Spinner } from '@/components/ui';
import { useLocalTools, useToolDetail } from '@/hooks/useLocalTools';
import {
  useMarketplaceListings,
  useMarketplaceTools,
  usePublishTool,
} from '@/hooks/useMarketplaceTools';
import { findMarketplaceTool } from '@/hooks/useMarketplaceTools';
import type { PricingModel, PublishToolPayload } from '@/types/marketplace';

type Step = 1 | 2 | 3 | 4 | 5;

const STEP_TITLES: Record<Step, string> = {
  1: 'Select Tool',
  2: 'Select Listing',
  3: 'Description',
  4: 'Pricing',
  5: 'Review & Publish',
};

export function PublishFlow() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialToolId = searchParams.get('toolId') ?? '';

  const [step, setStep] = useState<Step>(1);
  const [selectedToolId, setSelectedToolId] = useState<string>(initialToolId);
  const [listingId, setListingId] = useState<string>('');
  const [manualListingId, setManualListingId] = useState<string>('');
  const [nlDescription, setNlDescription] = useState<string>('');
  const [intendedUse, setIntendedUse] = useState<string>('');
  const [limitations, setLimitations] = useState<string>('');
  const [taxonomyTags, setTaxonomyTags] = useState<string>('');
  const [sampleIoText, setSampleIoText] = useState<string>('');
  const [pricingModel, setPricingModel] = useState<PricingModel>('per_call');
  const [priceCents, setPriceCents] = useState<string>('10');
  const [submitError, setSubmitError] = useState<string | null>(null);

  const localToolsQuery = useLocalTools();
  const marketplaceToolsQuery = useMarketplaceTools();
  const listingsQuery = useMarketplaceListings();
  const toolDetailQuery = useToolDetail(selectedToolId || undefined);
  const publishTool = usePublishTool();

  const publishableTools = useMemo(() => {
    const local = localToolsQuery.data?.tools ?? [];
    const marketTools = marketplaceToolsQuery.data?.tools ?? [];
    return local.filter((tool) => {
      const market = findMarketplaceTool(tool, marketTools);
      return !market || market.status === 'not_published';
    });
  }, [localToolsQuery.data?.tools, marketplaceToolsQuery.data?.tools]);

  const selectedTool = toolDetailQuery.data ?? null;

  const effectiveListingId = listingId || manualListingId.trim();

  function goNext() {
    setStep((prev) => (prev < 5 ? ((prev + 1) as Step) : prev));
  }
  function goPrev() {
    setStep((prev) => (prev > 1 ? ((prev - 1) as Step) : prev));
  }

  function canAdvance(): boolean {
    if (step === 1) return Boolean(selectedToolId);
    if (step === 2) return Boolean(effectiveListingId);
    if (step === 3) return nlDescription.trim().length > 0;
    if (step === 4) {
      const n = Number(priceCents);
      return Number.isFinite(n) && n >= 0;
    }
    return true;
  }

  function parseTaxonomy(): string[] {
    return taxonomyTags
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);
  }

  function parseSampleIo(): Array<Record<string, unknown>> {
    const trimmed = sampleIoText.trim();
    if (!trimmed) return [];
    try {
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) {
        return parsed.filter((v): v is Record<string, unknown> => Boolean(v) && typeof v === 'object');
      }
      return [];
    } catch {
      return [];
    }
  }

  function buildPayload(): PublishToolPayload | null {
    if (!selectedTool) return null;
    const priceNum = Number(priceCents);
    return {
      listing_id: effectiveListingId,
      tool_name: selectedTool.name,
      version: selectedTool.version,
      input_schema: selectedTool.input_schema ?? {},
      output_schema: selectedTool.output_schema ?? {},
      nl_description: nlDescription.trim(),
      pricing_formula: {
        model: pricingModel,
        price_cents: Number.isFinite(priceNum) ? priceNum : 0,
      },
      execution_mode: 'sync',
      task_taxonomy_tags: parseTaxonomy(),
      sample_io_pairs: parseSampleIo(),
      intended_use: intendedUse.trim() || undefined,
      limitations_and_known_failures: limitations.trim() || undefined,
    };
  }

  async function handlePublish() {
    const payload = buildPayload();
    if (!payload) return;
    setSubmitError(null);
    try {
      await publishTool.mutateAsync(payload);
      navigate(`/tools/${selectedToolId}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Publish failed';
      setSubmitError(message);
    }
  }

  const listingsData = listingsQuery.data?.listings ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Publish Tool"
        description={`Step ${step} of 5 — ${STEP_TITLES[step]}`}
        actions={
          <Button variant="ghost" onClick={() => navigate('/tools')}>
            Cancel
          </Button>
        }
      />

      <Card>
        {step === 1 && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-brand-text">Select a local tool</h2>
            {localToolsQuery.isLoading ? (
              <Spinner size="md" />
            ) : publishableTools.length === 0 ? (
              <p className="text-sm text-brand-text-secondary">
                No unpublished tools available. Run discovery on the tools page.
              </p>
            ) : (
              <Field label="Tool">
                <select
                  aria-label="Tool"
                  value={selectedToolId}
                  onChange={(e) => setSelectedToolId(e.target.value)}
                  className="rounded-brand border border-[#E8E8E8] px-3 py-2 text-sm"
                >
                  <option value="">-- Select a tool --</option>
                  {publishableTools.map((tool) => (
                    <option key={tool.tool_id} value={tool.tool_id}>
                      {tool.name} (v{tool.version})
                    </option>
                  ))}
                </select>
              </Field>
            )}
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-brand-text">Select a listing</h2>
            {listingsQuery.isLoading ? (
              <Spinner size="md" />
            ) : (
              <Field label="Existing listings">
                <select
                  aria-label="Listing"
                  value={listingId}
                  onChange={(e) => {
                    setListingId(e.target.value);
                    if (e.target.value) setManualListingId('');
                  }}
                  className="rounded-brand border border-[#E8E8E8] px-3 py-2 text-sm"
                >
                  <option value="">-- Choose listing --</option>
                  {listingsData.map((listing) => (
                    <option key={listing.listing_id} value={listing.listing_id}>
                      {listing.title ?? listing.listing_id}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <Input
              label="Or enter listing ID"
              placeholder="listing-uuid"
              value={manualListingId}
              onChange={(e) => {
                setManualListingId(e.target.value);
                if (e.target.value) setListingId('');
              }}
            />
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-brand-text">Describe the tool</h2>
            <Field label="Natural language description (required)">
              <textarea
                aria-label="Natural language description"
                value={nlDescription}
                onChange={(e) => setNlDescription(e.target.value)}
                rows={4}
                className="rounded-brand border border-[#E8E8E8] px-3 py-2 text-sm"
              />
            </Field>
            <Field label="Intended use">
              <textarea
                aria-label="Intended use"
                value={intendedUse}
                onChange={(e) => setIntendedUse(e.target.value)}
                rows={2}
                className="rounded-brand border border-[#E8E8E8] px-3 py-2 text-sm"
              />
            </Field>
            <Field label="Limitations and known failures">
              <textarea
                aria-label="Limitations"
                value={limitations}
                onChange={(e) => setLimitations(e.target.value)}
                rows={2}
                className="rounded-brand border border-[#E8E8E8] px-3 py-2 text-sm"
              />
            </Field>
            <Input
              label="Task taxonomy tags (comma-separated)"
              placeholder="summarization, extraction"
              value={taxonomyTags}
              onChange={(e) => setTaxonomyTags(e.target.value)}
            />
            <Field label="Sample I/O pairs (JSON array)">
              <textarea
                aria-label="Sample IO pairs"
                value={sampleIoText}
                onChange={(e) => setSampleIoText(e.target.value)}
                rows={3}
                placeholder='[{"input": {}, "output": {}}]'
                className="rounded-brand border border-[#E8E8E8] px-3 py-2 text-sm font-mono"
              />
            </Field>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-brand-text">Pricing</h2>
            <Field label="Pricing model">
              <select
                aria-label="Pricing model"
                value={pricingModel}
                onChange={(e) => setPricingModel(e.target.value as PricingModel)}
                className="rounded-brand border border-[#E8E8E8] px-3 py-2 text-sm"
              >
                <option value="per_call">per_call</option>
                <option value="per_minute">per_minute</option>
                <option value="flat_monthly">flat_monthly</option>
              </select>
            </Field>
            <Input
              label="Price (cents)"
              type="number"
              min="0"
              value={priceCents}
              onChange={(e) => setPriceCents(e.target.value)}
            />
          </div>
        )}

        {step === 5 && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-brand-text">Review</h2>
            {selectedTool ? (
              <dl className="grid gap-2 text-sm">
                <div>
                  <dt className="font-medium">Tool</dt>
                  <dd>
                    {selectedTool.name} v{selectedTool.version}
                  </dd>
                </div>
                <div>
                  <dt className="font-medium">Listing</dt>
                  <dd>{effectiveListingId}</dd>
                </div>
                <div>
                  <dt className="font-medium">Description</dt>
                  <dd>{nlDescription}</dd>
                </div>
                <div>
                  <dt className="font-medium">Pricing</dt>
                  <dd>
                    {pricingModel} · {priceCents} cents
                  </dd>
                </div>
              </dl>
            ) : (
              <Spinner size="md" />
            )}
            {submitError && (
              <p role="alert" className="text-sm text-brand-error">
                {submitError}
              </p>
            )}
          </div>
        )}
      </Card>

      <div className="flex items-center justify-between">
        <Button variant="ghost" onClick={goPrev} disabled={step === 1}>
          Back
        </Button>
        {step < 5 ? (
          <Button variant="primary" onClick={goNext} disabled={!canAdvance()}>
            Next
          </Button>
        ) : (
          <Button
            variant="primary"
            loading={publishTool.isPending}
            disabled={!selectedTool || !canAdvance()}
            onClick={handlePublish}
          >
            Publish
          </Button>
        )}
      </div>
    </div>
  );
}
