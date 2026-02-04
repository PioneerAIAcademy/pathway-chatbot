export enum FeedbackValue {
    EMPTY = '',
    GOOD = 'Good',
    BAD = 'Bad',
}

export const sendUserFeedback = async (backend: string, traceId: string, value: FeedbackValue) => {
    const uploadAPI = `${backend}/api/chat/thumbs_request`;
    const body = {
        trace_id: traceId,
        value: value
    };

    const response = await fetch(uploadAPI, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
    });

    if (!response.ok) {
        throw new Error("Failed to send feedback");
    }

    // Keep response for future use (no console logging).
    return response.json().catch(() => null);
};
