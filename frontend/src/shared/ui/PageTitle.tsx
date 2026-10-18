import type { ReactNode } from 'react';

export function PageTitle({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <div className="sw-page-title">
      <div>
        <h1 tabIndex={-1}>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {children ??
        (import.meta.env.DEV && import.meta.env.VITE_ENABLE_MOCKS === 'true' ? (
          <span className="sw-preview">Preview</span>
        ) : null)}
    </div>
  );
}
