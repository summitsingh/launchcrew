import { ReviewWorkspace } from '@/components/demo/demo-review';

export default async function JudgesReviewPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  return <ReviewWorkspace runId={runId} />;
}
