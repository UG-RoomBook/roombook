import { cva } from 'class-variance-authority';
import { useEffect, useState, type ComponentProps } from 'react';
import { cn } from './cn';

const buttonVariants = cva('sw-btn', {
  variants: { variant: { primary: 'sw-primary', secondary: '' } },
  defaultVariants: { variant: 'secondary' },
});

export function Button({
  variant = 'secondary',
  className,
  children,
  onClick,
  type = 'button',
  ...props
}: ComponentProps<'button'> & { variant?: 'primary' | 'secondary' }) {
  const [ripple, setRipple] = useState<{ x: number; y: number; id: number } | null>(null);
  useEffect(() => {
    if (!ripple) return;
    const timeout = window.setTimeout(() => setRipple(null), 600);
    return () => window.clearTimeout(timeout);
  }, [ripple]);
  return (
    <button
      {...props}
      type={type}
      className={cn(buttonVariants({ variant }), className)}
      onClick={(event) => {
        if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
          const bounds = event.currentTarget.getBoundingClientRect();
          setRipple({
            x: event.detail ? event.clientX - bounds.left : bounds.width / 2,
            y: event.detail ? event.clientY - bounds.top : bounds.height / 2,
            id: event.timeStamp,
          });
        }
        onClick?.(event);
      }}
    >
      {children}
      {ripple && (
        <span
          key={ripple.id}
          className="sw-ripple"
          aria-hidden="true"
          style={{ left: ripple.x, top: ripple.y }}
          onAnimationEnd={() => setRipple(null)}
        />
      )}
    </button>
  );
}
