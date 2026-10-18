import { Monitor, Moon, Sun } from 'lucide-react';
import type { CSSProperties } from 'react';
import { useTheme } from './theme-context';

const options = [
  { value: 'light', label: 'Light', Icon: Sun },
  { value: 'dark', label: 'Dark', Icon: Moon },
  { value: 'system', label: 'System', Icon: Monitor },
] as const;

export function AppearanceControl() {
  const { appearance, setAppearance } = useTheme();
  const index = options.findIndex((option) => option.value === appearance);
  return (
    <div
      className="sw-appearance"
      role="group"
      aria-label="Appearance"
      style={{ '--theme-index': `${index * 100}%` } as CSSProperties}
    >
      {options.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          aria-pressed={appearance === value}
          onClick={() => setAppearance(value)}
        >
          <Icon aria-hidden="true" />
          {label}
        </button>
      ))}
    </div>
  );
}
