import { Upload, FileText } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

export default function LibraryPage() {
  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-1.5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-2xl font-medium tracking-tight">
            Library
          </h1>
          <p className="text-sm text-muted-foreground">
            Upload documents to make them searchable in Chat.
          </p>
        </div>
        <Button>
          <Upload className="size-4" />
          Upload document
        </Button>
      </div>

      <Separator />

      <Card className="border-dashed">
        <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
          <div className="flex size-12 items-center justify-center rounded-full bg-muted">
            <FileText className="size-5 text-muted-foreground" />
          </div>
          <CardHeader className="gap-1 p-0">
            <CardTitle className="text-base font-medium">
              No documents yet
            </CardTitle>
            <CardDescription>
              PDF, DOCX, HTML, or Markdown — upload your first file to get
              started.
            </CardDescription>
          </CardHeader>
          <Button variant="outline" size="sm" className="mt-2">
            <Upload className="size-4" />
            Upload document
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
