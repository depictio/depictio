import { ReactNode, useEffect } from "react";
import { Navigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Center, Loader } from "@mantine/core";
import { useAuthStore } from "../store/auth";
import { fetchMe } from "../api/auth";

interface Props {
  children: ReactNode;
}

export default function ProtectedRoute({ children }: Props) {
  const { accessToken, user, setUser, clear } = useAuthStore();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["me", accessToken],
    queryFn: fetchMe,
    enabled: Boolean(accessToken) && !user,
  });

  useEffect(() => {
    if (data) setUser(data);
    if (isError) clear();
  }, [data, isError, setUser, clear]);

  if (!accessToken) {
    return <Navigate to="/auth" replace />;
  }
  if (isLoading && !user) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }
  return <>{children}</>;
}
