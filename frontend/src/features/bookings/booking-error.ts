import { ApiError } from '@/shared/api/client';

export type BookingFeedback = {
  title: string;
  message: string;
  uncertain: boolean;
};

export function bookingFeedback(error: unknown): BookingFeedback {
  if (error instanceof ApiError && error.uncertain) {
    return {
      title: 'Booking outcome not confirmed',
      message:
        'The request may have completed. Check bookings before creating another booking for this room and time.',
      uncertain: true,
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
