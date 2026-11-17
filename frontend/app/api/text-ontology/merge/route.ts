// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// Merge extracted ontologies into one. Pure computation on the request body:
// no store access and no LLM call.
export const POST = withPermission({ catalog: ['read'] })((req) => proxyToBackend(req));
