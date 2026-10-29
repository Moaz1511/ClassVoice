import { PlaceholderPage } from "../../../components/ui/PlaceholderPage";

type PlaceholderRouteProps = Readonly<{
  params: Promise<{ slug: string[] }>;
}>;

export default async function ProtectedPlaceholderRoute({ params }: PlaceholderRouteProps) {
  const { slug } = await params;
  return <PlaceholderPage route={slug.join("/")} />;
}
