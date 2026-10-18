import { Button } from './Button';

export function StateMessage({
  title,
  message,
  onRetry,
  variant = 'status',
}: {
  title: string;
  message?: string;
  onRetry?: () => void;
  variant?: 'status' | 'error';
}) {
  return (
    <div className="sw-empty sw-state" role={variant === 'error' ? 'alert' : 'status'}>
      <h2>{title}</h2>
      {message && <p className="sw-small">{message}</p>}
      {onRetry && <Button onClick={onRetry}>Try again</Button>}
    </div>
  );
}
