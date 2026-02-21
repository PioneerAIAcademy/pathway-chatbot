export enum FeedbackValue {
    EMPTY = '',
    GOOD = 'Good',
    BAD = 'Bad',
}

export const sendUserFeedback = async (
    backend: string, 
    traceId: string, 
    value: FeedbackValue,
    comment?: string
): Promise<boolean> => {
    const uploadAPI = `${backend}/api/chat/thumbs_request`;
    try {
        const body: { trace_id: string; value: FeedbackValue; comment?: string } = {
            trace_id: traceId,
            value: value
        };

        // Include `comment` even if it's an empty string so the backend/Langfuse can clear
        // a previously submitted comment when users switch from Bad -> Good.
        if (comment !== undefined) {
            body.comment = comment;
        }

        const response = await fetch(uploadAPI, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-API-Key": process.env.NEXT_PUBLIC_API_KEY ?? "",
            },
            body: JSON.stringify(body),
        });

        if (!response.ok) {
            throw new Error("Failed to send feedback");
        }

        // Consume the response body to avoid noisy "unhandled" warnings in some browsers.
        await response.json().catch(() => null);
        return true;
    } catch (error) {
        // Intentionally no console output (this component lives in the user-facing UI).
        return false;
    }
};
