import type{
    DeleteResponse,
    Document,
    IngestJobResponse,
    JobStatusOut
} from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | undefined;

  constructor(status: number, detail: string | undefined, fallbackMessage: string) {
    super(detail ?? fallbackMessage);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T>{
    let response: Response;

    try{
        response = await fetch(`${API_URL}${path}`, init);
    } catch(cause){
        throw new ApiError(0, undefined, `could not reach the API at ${API_URL}. Is the server running?`)
    };
    
}