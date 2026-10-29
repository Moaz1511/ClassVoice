import { StudioScreen } from "../../../../components/studio/StudioScreen";

type StudioProjectRouteProps = Readonly<{
  params: Promise<{ projectId: string }>;
}>;

export const metadata = { title: "Studio project" };

export default async function StudioProjectPage({ params }: StudioProjectRouteProps) {
  const { projectId } = await params;
  return <StudioScreen projectId={projectId} />;
}
