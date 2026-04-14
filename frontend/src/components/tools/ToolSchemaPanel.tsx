import { Card } from '@/components/ui';

interface ToolSchemaPanelProps {
  title: string;
  schema: Record<string, unknown>;
}

export function ToolSchemaPanel({ title, schema }: ToolSchemaPanelProps) {
  return (
    <Card className="h-full">
      <div className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-brand-text">{title}</h2>
          <p className="text-xs text-brand-text-secondary">JSON schema from the local tool scan.</p>
        </div>
        <pre className="max-h-96 overflow-auto rounded-brand bg-brand-surface p-4 text-xs leading-6 text-brand-text">
          {JSON.stringify(schema, null, 2)}
        </pre>
      </div>
    </Card>
  );
}

