import { ApiError } from '@/shared/api/client';

export type BookingFeedback = {
  title: string;
  message: string;
  uncertain: boolean;
};

export function bookingFeedback(error: unknown): BookingFeedback {
  if (error instanceof ApiError && error.code === 'FEATURE_NOT_AVAILABLE') {
    return {
      title: 'Booking is not available yet',
      message: error.message,
      uncertain: false,
    };
  }
  if (error instanceof ApiError && error.uncertain) {
    return {
      title: 'Booking outcome not confirmed',
      message:
        'The request may have completed. Retry this saved attempt to confirm the original result. Keep this tab until the outcome is known.',
      uncertain: true,
    };
  }
  if (
    error instanceof ApiError &&
    ['ATTEMPT_STORAGE', 'IDEMPOTENCY_MISMATCH'].includes(error.code)
  ) {
    return { title: 'Saved attempt needs attention', message: error.message, uncertain: false };
  }
  if (error instanceof ApiError && [401, 403, 429].includes(error.status)) {
    return {
      title:
        error.status === 401
          ? 'Sign in to book'
          : error.status === 403
            ? 'Booking access denied'
            : 'Please wait before retrying',
      message:
        error.status === 403
          ? 'A verified, active account and a valid session are required. Check your account and try again.'
          : error.message,
      uncertain: false,
    };
  }
  if (error instanceof ApiError && error.status === 409) {
    return {
      title: 'Room no longer available',
      message:
        'The room or selected time is unavailable. Your selection is kept. Choose another room or time.',
      uncertain: false,
    };
  }
  if (error instanceof ApiError && error.status === 404) {
    return {
      title: 'Room not found',
      message: 'Return to the room search and choose an available room.',
      uncertain: false,
    };
  }
  if (error instanceof ApiError && error.status === 422) {
    return {
      title: 'Check the booking details',
      message: error.message,
      uncertain: false,
    };
  }
  return {
    title: 'Booking could not be confirmed',
    message: 'Your selection is kept. Try again when the service is available.',
    uncertain: false,
  };
}

export function cancellationFeedback(error: unknown): BookingFeedback {
  if (error instanceof ApiError && error.code === 'FEATURE_NOT_AVAILABLE') {
    return {
      title: 'Cancellation is not available yet',
      message: error.message,
      uncertain: false,
    };
  }
  if (error instanceof ApiError && error.uncertain) {
    return {
      title: 'Cancellation outcome not confirmed',
      message: 'The request may have completed. Refresh bookings to check the reservation status.',
      uncertain: true,
    };
  }
  return {
    title: 'Booking could not be cancelled',
    message:
      error instanceof ApiError && error.status === 404
        ? 'This reservation was not found. Refresh bookings to check the latest records.'
        : 'The reservation has not been confirmed as cancelled. You can try again.',
    uncertain: false,
  };
}
