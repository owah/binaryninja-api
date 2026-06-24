// Copyright 2016-2026 Vector 35 Inc.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#pragma once

#include <cstddef>
#include <exception>
#include <utility>

class DemangleException: public std::exception
{
	_STD_STRING m_message;

public:
	DemangleException(_STD_STRING msg = "Attempt to read beyond bounds or missing expected character"):
		m_message(std::move(msg))
	{}

	[[nodiscard]] const char* what() const noexcept override { return m_message.c_str(); }
};

static constexpr size_t MaxDemangleNestingDepth = 1024;

class DemangleNestingGuard
{
	size_t& m_nestingDepth;

public:
	explicit DemangleNestingGuard(size_t& nestingDepth) : m_nestingDepth(nestingDepth)
	{
		m_nestingDepth++;
		if (m_nestingDepth > MaxDemangleNestingDepth)
		{
			m_nestingDepth--;
			throw DemangleException("Detected adversarial mangled string");
		}
	}

	~DemangleNestingGuard()
	{
		m_nestingDepth--;
	}

	DemangleNestingGuard(const DemangleNestingGuard&) = delete;
	DemangleNestingGuard& operator=(const DemangleNestingGuard&) = delete;
};
