import { describe, expect, it } from 'vitest';
import { ApiError } from '@/shared/api/client';
import { bookingFeedback, cancellationFeedback } from './booking-error';

describe('pending booking API feedback', () => {
  const error = new ApiError(
    'Booking is not available yet. You can search rooms and check availability.',
    { status: 501, code: 'FEATURE_NOT_AVAILABLE' },
  );

  it('states that booking is unavailable without suggesting an uncertain submission or retry', () => {
    expect(bookingFeedback(error)).toEqual({
      title: 'Booking is not available yet',
      message: error.message,
      uncertain: false,
    });
  });

  it('preserves the unavailable reason for cancellation', () => {
    expect(cancellationFeedback(error)).toEqual({
      title: 'Cancellation is not available yet',
      message: error.message,
      uncertain: false,
    });
  });
});
