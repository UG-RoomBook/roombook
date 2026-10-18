import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Button } from './Button';

describe('Button', () => {
  it('invokes its action once and removes its ripple after animation', () => {
    vi.useFakeTimers();
    const onClick = vi.fn();
    render(
      <Button variant="primary" onClick={onClick}>
        Book room
      </Button>,
    );
    const button = screen.getByRole('button', { name: 'Book room' });
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
    expect(button).toHaveClass('sw-primary');
    const ripple = button.querySelector('.sw-ripple');
    expect(ripple).not.toBeNull();
    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(button.querySelector('.sw-ripple')).toBeNull();
    vi.useRealTimers();
  });

  it('does not invoke a disabled action', () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Confirm booking
      </Button>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Confirm booking' }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it('skips decorative ripple for reduced motion', () => {
    const matchMedia = vi
      .spyOn(window, 'matchMedia')
      .mockReturnValue({ matches: true } as MediaQueryList);
    render(<Button>Back</Button>);
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByRole('button', { name: 'Back' }).querySelector('.sw-ripple')).toBeNull();
    matchMedia.mockRestore();
  });
});
