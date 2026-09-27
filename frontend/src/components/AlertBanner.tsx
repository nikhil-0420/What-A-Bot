import './portal.css';

export type AlertBannerProps = {
  title: string;
  message: string;
  code?: string;
  debugEndpoint?: string;
  onDismiss?: () => void;
  onRetry?: () => void;
  type?: 'error' | 'warning' | 'info';
};

export function AlertBanner({
  title,
  message,
  code,
  debugEndpoint,
  onDismiss,
  onRetry,
  type = 'error',
}: AlertBannerProps) {
  return (
    <div className={`alert-banner alert-banner--${type}`} role={type === 'error' ? 'alert' : 'status'}>
      <span className="alert-banner__mark" aria-hidden="true">{type === 'error' ? '!' : type === 'warning' ? '!' : 'i'}</span>
      <div className="alert-banner__content">
        <div className="alert-banner__heading">
          <strong>{title}</strong>
          {onRetry && <button className="alert-banner__action" type="button" onClick={onRetry}>Retry</button>}
        </div>
        <p>{message}</p>
        {code && <code className="alert-banner__code">{code}</code>}
        {debugEndpoint && <code className="alert-banner__endpoint">{debugEndpoint}</code>}
      </div>
      {onDismiss && (
        <button className="alert-banner__dismiss" type="button" onClick={onDismiss} aria-label="Dismiss notice">
          <span aria-hidden="true">x</span>
        </button>
      )}
    </div>
  );
}

export default AlertBanner;