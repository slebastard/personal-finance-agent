import { ArgumentsHost, Catch, ExceptionFilter, HttpException, Logger } from '@nestjs/common';
import type { ApiError } from '@pfa/contracts';

export class DomainError extends HttpException {
  constructor(public readonly code: string, message: string, status: number,
              public readonly details?: unknown) {
    super(message, status);
  }
}

export const notFound = (code: string, message: string, details?: unknown) =>
  new DomainError(code, message, 404, details);
export const badRequest = (message: string, details?: unknown) =>
  new DomainError('BAD_REQUEST', message, 400, details);
export const unavailable = (message: string) =>
  new DomainError('DB_UNAVAILABLE', message, 503);

/** One error shape for the whole API, so the client never has to guess. */
@Catch()
export class HttpErrorFilter implements ExceptionFilter {
  private readonly log = new Logger('error');

  catch(err: unknown, host: ArgumentsHost) {
    const res = host.switchToHttp().getResponse();
    if (err instanceof DomainError) {
      const body: ApiError = {
        error: { code: err.code, message: err.message, details: err.details },
      };
      return res.status(err.getStatus()).json(body);
    }
    if (err instanceof HttpException) {
      return res.status(err.getStatus())
        .json({ error: { code: 'HTTP_ERROR', message: err.message } } satisfies ApiError);
    }
    this.log.error(err instanceof Error ? err.stack ?? err.message : String(err));
    return res.status(500).json({
      error: { code: 'INTERNAL', message: 'unexpected server error' },
    } satisfies ApiError);
  }
}
