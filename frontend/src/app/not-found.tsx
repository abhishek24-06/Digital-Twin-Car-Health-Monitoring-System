import Link from "next/link";
import { Compass } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh items-center justify-center px-6">
      <div className="max-w-md text-center">
        <span className="mx-auto grid size-12 place-items-center rounded-xl bg-surface-3 text-ink-subtle">
          <Compass className="size-6" aria-hidden />
        </span>
        <h1 className="mt-4 text-lg font-semibold tracking-tight text-ink">
          This page does not exist
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-ink-subtle">
          The link may be out of date, or the vehicle it pointed at may have been
          deleted.
        </p>
        <div className="mt-5 flex justify-center gap-2">
          <Button asChild size="sm">
            <Link href="/dashboard">Go to dashboard</Link>
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link href="/vehicles">My vehicles</Link>
          </Button>
        </div>
      </div>
    </main>
  );
}
