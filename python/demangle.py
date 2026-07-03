# Copyright (c) 2015-2026 Vector 35 Inc
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to
# deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

import ctypes

# Binary Ninja components
import binaryninja
from . import _binaryninjacore as core
from . import binaryview
from . import types
from .log import log_error_for_exception
from .architecture import Architecture
from .platform import Platform
from .settings import Settings
from typing import Iterable, List, Optional, Union, Any, NamedTuple

_DEMANGLER_MSVC = "msvc"
_DEMANGLER_GNU3 = "gnu3"
_DEMANGLER_LLVM = "llvm"
_demangler_cache = {}


def _get_demangler_by_name(name: str):
	demangler = _demangler_cache.get(name)
	if demangler is not None:
		return demangler

	demangler = core.BNGetDemanglerByName(name)
	if demangler is not None:
		_demangler_cache[name] = demangler
	return demangler


class DemangleResult(NamedTuple):
	"""
	Tuple-compatible demangle result.
	"""

	type: Optional['types.Type']
	name: Union['types.QualifiedName', List[str], str]


def _demangle_result_from_core_and_free(
		result: core.BNDemanglerResult,
		qualified_name: bool = False
) -> DemangleResult:
	out_type = None
	try:
		if result.type:
			out_type = core.BNNewTypeReference(result.type)
		result_var_name = types.QualifiedName._from_core_struct(result.name)

		result_type = None
		if out_type:
			result_type = types.Type.create(handle=out_type)
			out_type = None
		result_name = result_var_name if qualified_name else result_var_name.name
		return DemangleResult(result_type, result_name)
	finally:
		if out_type:
			core.BNFreeType(out_type)
		core.BNFreeDemanglerResult(result)


class DemanglerConfig:
	"""
	Configuration used by demangler APIs.
	"""

	def __init__(
			self,
			arch_or_platform: Optional[Union[Architecture, Platform]] = None,
			view: Optional['binaryview.BinaryView'] = None,
			simplify: bool = False
	):
		if isinstance(arch_or_platform, Architecture):
			platform_obj = arch_or_platform.standalone_platform
		elif isinstance(arch_or_platform, Platform):
			platform_obj = arch_or_platform
		elif arch_or_platform is None:
			platform_obj = view.platform if view is not None else None
		else:
			raise TypeError("Unexpected arch or platform type")

		self.platform = platform_obj
		self.view = view
		self.simplify_templates = simplify

	def _to_core_struct(self) -> core.BNDemanglerConfig:
		config = core.BNDemanglerConfig()
		config.platform = self.platform.handle if self.platform is not None else None
		config.view = self.view.handle if self.view is not None else None
		config.simplifyTemplates = self.simplify_templates
		return config

	@classmethod
	def _from_core_struct(cls, config: core.BNDemanglerConfig) -> 'DemanglerConfig':
		if hasattr(config, "contents"):
			config = config.contents

		platform = None
		if config.platform:
			platform = Platform(handle=core.BNNewPlatformReference(config.platform))

		view = None
		if config.view:
			view = binaryview.BinaryView(handle=core.BNNewViewReference(config.view))

		return cls(platform, view, config.simplifyTemplates)


def get_qualified_name(names: Iterable[str]):
	"""
	``get_qualified_name`` gets a qualified name for the provided name list.

	:param names: name list to qualify
	:type names: list(str)
	:return: a qualified name
	:rtype: str
	:Example:

		>>> result = demangle_ms(Architecture["x86_64"], "?testf@Foobar@@SA?AW4foo@1@W421@@Z")
		>>> get_qualified_name(result.name)
		'Foobar::testf'
		>>>
	"""
	return "::".join(names)


def demangle_any(
		mangled_name: str,
		config: DemanglerConfig
) -> Optional[DemangleResult]:
	"""
	``demangle_any`` demangles a mangled symbol name using a prebuilt demangler config.

	:param str mangled_name: a mangled symbol name
	:param DemanglerConfig config: Platform/view/options used while demangling
	:return: returns a DemangleResult with type and name fields, or None on error. DemangleResult can be unpacked as (type, name).
	:rtype: Optional[DemangleResult]
	:Example:

		>>> config = DemanglerConfig(Architecture["x86_64"])
		>>> result = demangle_any("?testf@Foobar@@SA?AW4foo@1@W421@@Z", config)
		>>> result.type
		<type: immutable:FunctionTypeClass 'enum Foobar::foo __cdecl(enum Foobar::foo)'>
		>>> result.name
		['Foobar', 'testf']
	"""
	if not isinstance(config, DemanglerConfig):
		raise TypeError("config must be a DemanglerConfig")

	result = core.BNDemanglerResult()
	api_config = config._to_core_struct()
	if not core.BNDemangle(mangled_name, api_config, result):
		return None

	try:
		return _demangle_result_from_core_and_free(result)
	except UnicodeDecodeError:
		return None


def demangle_generic(
		archOrPlatform: Union[Architecture, Platform],
		mangled_name: str,
		view: Optional['binaryview.BinaryView'] = None,
		simplify: bool = False
) -> DemangleResult:
	"""
	``demangle_generic`` demangles a mangled symbol name to a Type object.

	:param Union[Architecture, Platform] archOrPlatform: Architecture or Platform for the symbol. Required for pointer/integer sizes and calling conventions.
	:param str mangled_name: a mangled symbol name
	:param view: (optional) view of the binary containing the mangled name
	:param simplify: (optional) Whether to simplify demangled names
	:return: returns a DemangleResult with type and name fields. DemangleResult can be unpacked as (type, name).
	:rtype: DemangleResult
	:Example:

		>>> demangle_generic(Architecture["x86_64"], "?testf@Foobar@@SA?AW4foo@1@W421@@Z")
		DemangleResult(type=<type: immutable:FunctionTypeClass 'enum Foobar::foo __cdecl(enum Foobar::foo)'>, name=['Foobar', 'testf'])
		>>> demangle_generic(Architecture["x86_64"], "__ZN20ArmCallingConvention27GetIntegerArgumentRegistersEv")
		DemangleResult(type=<type: immutable:FunctionTypeClass 'int64_t()'>, name=['ArmCallingConvention', 'GetIntegerArgumentRegisters'])
		>>>
	"""
	config = DemanglerConfig(archOrPlatform, view, simplify)
	return demangle_any(mangled_name, config) or DemangleResult(None, [mangled_name])


def demangle_llvm(mangled_name: str, options: Optional[Union[bool, binaryview.BinaryView]] = None) -> Optional[List[str]]:
	"""
	``demangle_llvm`` demangles a mangled name using the LLVM demangler.

	:param str mangled_name: a mangled (msvc/gnu3/rust/dlang) name
	:param options: (optional) Whether to simplify demangled names : None falls back to user settings, a BinaryView uses that BinaryView's settings, or a boolean to set it directly
	:type options: Optional[Union[bool, BinaryView]]
	:return: returns demangled name or None on error
	:rtype: Optional[List[str]]
	:Example:

		>>> demangle_llvm("?testf@Foobar@@SA?AW4foo@1@W421@@Z")
		['public: static enum Foobar::foo __cdecl Foobar::testf(enum Foobar::foo)']
		>>>
	"""
	view, simplify_templates = _simplify_from_compat_option(options)
	config = DemanglerConfig(view=view, simplify=simplify_templates)._to_core_struct()

	demangler = _get_demangler_by_name(_DEMANGLER_LLVM)
	if demangler is None:
		return None

	result = core.BNDemanglerResult()
	if not core.BNDemangleWithDemangler(demangler, mangled_name, config, result):
		return None

	return _demangle_result_from_core_and_free(result).name


def _simplify_from_compat_option(simplify: Optional[Union[bool, binaryview.BinaryView]]):
	if isinstance(simplify, binaryview.BinaryView):
		return simplify, Settings().get_bool("analysis.types.templateSimplifier", simplify)
	if simplify is None:
		return None, Settings().get_bool("analysis.types.templateSimplifier")
	if isinstance(simplify, bool):
		return None, simplify
	raise TypeError("simplify must be a bool")


def _demangle_type_and_name(
		arch_or_platform: Union[Architecture, Platform],
		mangled_name: str,
		simplify: Optional[Union[bool, binaryview.BinaryView]],
		demangler_name: str
) -> DemangleResult:
	view, simplify_templates = _simplify_from_compat_option(simplify)

	binaryninja._init_plugins()
	demangler = _get_demangler_by_name(demangler_name)
	if demangler is None:
		return DemangleResult(None, mangled_name)

	config = DemanglerConfig(arch_or_platform, view, simplify_templates)._to_core_struct()
	result = core.BNDemanglerResult()
	if not core.BNDemangleWithDemangler(demangler, mangled_name, config, result):
		return DemangleResult(None, mangled_name)

	return _demangle_result_from_core_and_free(result)


def demangle_ms(
		arch_or_platform: Union[Architecture, Platform],
		mangled_name: str,
		simplify: bool = False
) -> DemangleResult:
	"""
	``demangle_ms`` demangles a mangled Microsoft Visual Studio C++ name to a Type object.

	:param Union[Architecture, Platform] arch_or_platform: Architecture or Platform for the symbol. Required for pointer/integer sizes and calling conventions.
	:param str mangled_name: a mangled Microsoft Visual Studio C++ name
	:param bool simplify: (optional) Whether to simplify demangled names
	:return: returns a DemangleResult with type and name fields, or DemangleResult(None, mangled_name) on error
	:rtype: DemangleResult
	:Example:

		>>> demangle_ms(Architecture["x86_64"], "?testf@Foobar@@SA?AW4foo@1@W421@@Z")
		DemangleResult(type=<type: immutable:FunctionTypeClass 'enum Foobar::foo __cdecl(enum Foobar::foo)'>, name=['Foobar', 'testf'])
		>>>
	"""
	return _demangle_type_and_name(arch_or_platform, mangled_name, simplify, _DEMANGLER_MSVC)


def demangle_gnu3(
		arch_or_platform: Union[Architecture, Platform],
		mangled_name: str,
		simplify: bool = False
) -> DemangleResult:
	"""
	``demangle_gnu3`` demangles a mangled name to a Type object.

	:param Union[Architecture, Platform] arch_or_platform: Architecture or Platform for the symbol. Required for pointer and integer sizes.
	:param str mangled_name: a mangled GNU3 name
	:param bool simplify: (optional) Whether to simplify demangled names
	:return: returns a DemangleResult with type and name fields, or DemangleResult(None, mangled_name) on error
	:rtype: DemangleResult
	"""
	return _demangle_type_and_name(arch_or_platform, mangled_name, simplify, _DEMANGLER_GNU3)


class _DemanglerMetaclass(type):
	def __iter__(self):
		binaryninja._init_plugins()
		count = ctypes.c_ulonglong()
		types = core.BNGetDemanglerList(count)
		try:
			for i in range(0, count.value):
				yield CoreDemangler(types[i])
		finally:
			core.BNFreeDemanglerList(types)

	def __getitem__(self, value):
		binaryninja._init_plugins()
		handle = _get_demangler_by_name(str(value))
		if handle is None:
			raise KeyError(f"'{value}' is not a valid Demangler")
		return CoreDemangler(handle)

	def __contains__(cls: '_DemanglerMetaclass', name: object) -> bool:
		if not isinstance(name, str):
			return False
		try:
			cls[name]
			return True
		except KeyError:
			return False

	def get(cls: '_DemanglerMetaclass', name: str, default: Any = None) -> Optional['Demangler']:
		try:
			return cls[name]
		except KeyError:
			if default is not None:
				return default
			return None


class Demangler(metaclass=_DemanglerMetaclass):
	"""
	Pluggable name demangling interface. See :py:func:`register` and :py:func:`demangle`
	for details on the process of this interface.

	Custom Demangler subclasses must be registered during plugin initialization. After
	plugin loading completes, the demangler registry is finalized so named lookups and
	priority order can be cached efficiently. Registration and promotion attempts after
	that point return False. In practice, this means Python demanglers should call
	``MyDemangler.register()`` from plugin module initialization, before APIs such as
	``list(Demangler)``, ``Demangler["name"]``, or opening a view trigger plugin
	initialization.

	The list of Demanglers can be queried:

		>>> list(Demangler)
		[<Demangler: msvc>, <Demangler: gnu3>, <Demangler: llvm>]
	"""

	name = None
	_registered_demanglers = []
	_cached_name = None

	def __init__(self, handle=None):
		if handle is not None:
			self.handle = core.handle_of_type(handle, core.BNDemangler)
			self.__dict__["name"] = core.BNGetDemanglerName(handle)
		else:
			self.handle = None

	@classmethod
	def register(cls):
		"""
		Register a custom Demangler. Newly registered demanglers will get priority over
		previously registered demanglers and built-in demanglers.

		Demanglers must be registered during plugin initialization. After plugin loading
		completes, the demangler registry is finalized so named lookups and priority order
		can be cached efficiently, and further registration attempts fail.

		:return: True if registration succeeded; False if the demangler was invalid or
		         registration has already been finalized.
		"""
		demangler = cls()

		assert demangler.__class__.name is not None
		assert demangler.handle is None

		demangler._cb = core.BNDemanglerCallbacks()
		demangler._cb.size = ctypes.sizeof(core.BNDemanglerCallbacks)
		demangler._cb.context = 0
		demangler._cb.isMangledString = demangler._cb.isMangledString.__class__(demangler._is_mangled_string)
		demangler._cb.demangle = demangler._cb.demangle.__class__(demangler._demangle)
		demangler._cb.freeResult = demangler._cb.freeResult.__class__(demangler._free_result)
		demangler.handle = core.BNRegisterDemangler(cls.name, demangler._cb)
		if not demangler.handle:
			return False

		cls._registered_demanglers.append(demangler)
		return True

	@classmethod
	def promote(cls, demangler):
		"""
		Promote a demangler to the highest-priority position.

		Demanglers must be promoted during plugin initialization. After plugin loading
		completes, the demangler registry is finalized so priority order can be cached
		efficiently, and further promotion attempts fail.

		:param demangler: Demangler to promote
		:return: True if promotion succeeded; False if the demangler was invalid or
		         promotion has already been finalized.
		"""
		if demangler is None or demangler.handle is None:
			return False
		return core.BNPromoteDemangler(demangler.handle)

	def __eq__(self, other):
		if not isinstance(other, Demangler):
			return False
		return self.name == other.name

	def __str__(self):
		return f'<Demangler: {self.name}>'

	def __repr__(self):
		return f'<Demangler: {self.name}>'

	def _is_mangled_string(self, ctxt, name):
		try:
			return self.is_mangled_string(core.pyNativeStr(name))
		except Exception:
			log_error_for_exception("Unhandled Python exception in Demangler._is_mangled_string")
			return False

	def _demangle(self, ctxt, name, config, result):
		try:
			api_config = DemanglerConfig._from_core_struct(config)

			demangle_result = self.demangle(core.pyNativeStr(name), api_config)
			if demangle_result is None:
				return False
			type, var_name = demangle_result

			if not isinstance(var_name, types.QualifiedName):
				var_name = types.QualifiedName(var_name)

			Demangler._cached_name = core.BNDemanglerResult()
			Demangler._cached_name.name = var_name._to_core_struct()
			if type is not None:
				Demangler._cached_name.type = core.BNNewTypeReference(type.handle)
			else:
				Demangler._cached_name.type = None
			result[0] = Demangler._cached_name
			return True
		except Exception:
			log_error_for_exception("Unhandled Python exception in Demangler._demangle")
			return False

	def _free_result(self, ctxt, result):
		try:
			if result is not None and result.contents.type:
				core.BNFreeType(result.contents.type)
			Demangler._cached_name = None
		except Exception:
			log_error_for_exception("Unhandled Python exception in Demangler._free_result")

	def is_mangled_string(self, name: str) -> bool:
		"""
		Determine if a given name is mangled and this demangler can process it

		The most recently registered demangler that claims a name is a mangled string
		(returns true from this function), and then returns a value from
		:py:func:`demangle` will determine the result of a call to :py:func:`demangle_generic`.
		Returning True from this does not require the demangler to succeed the call to
		:py:func:`demangle`, but simply implies that it may succeed.

		:param name: Raw mangled name string
		:return: True if the demangler thinks it can handle the name
		"""
		raise NotImplementedError()

	def demangle(
			self,
			name: str,
			config: DemanglerConfig
	) -> Optional[DemangleResult]:
		"""
		Demangle a raw name into a Type and QualifiedName.

		The result of this function is a DemangleResult with Type and QualifiedName
		fields for the demangled name's details. DemangleResult can be unpacked as
		(type, name).

		Any unresolved named types referenced by the resulting Type will be created as
		empty structures or void typedefs in the view, if the result is used on
		a data structure in the view. Given this, the call to :py:func:`demangle`
		should NOT cause any side-effects creating types in the view trying to resolve this
		and instead just return a type with unresolved named type references.

		The most recently registered demangler that claims a name is a mangled string
		(returns true from :py:func:`is_mangled_string`), and then returns a value from
		this function will determine the result of a call to :py:func:`demangle_generic`.
		If this call returns None, the next most recently used demangler(s) will be tried instead.

		If the mangled name has no type information, but a name is still possible to extract,
		this function may return a successful DemangleResult(None, <name>), which will be accepted.

		:param name: Raw mangled name
		:param config: Platform/view/options used while demangling
		:return: DemangleResult with type and name fields if successful, None if not.
		         Type may be None if only a demangled name can be recovered from the raw name.
		"""
		raise NotImplementedError()

	@staticmethod
	def demangle_any(name: str, config: DemanglerConfig) -> Optional[DemangleResult]:
		"""
		Demangle a raw name using a prebuilt DemanglerConfig.
		"""
		return demangle_any(name, config)


class CoreDemangler(Demangler):

	def is_mangled_string(self, name: str) -> bool:
		return core.BNIsDemanglerMangledName(self.handle, name)

	def demangle(self, name: str, config: DemanglerConfig) -> Optional[DemangleResult]:
		result = core.BNDemanglerResult()
		api_config = config._to_core_struct()

		if not core.BNDemangleWithDemangler(self.handle, name, api_config, result):
			return None

		return _demangle_result_from_core_and_free(result, qualified_name=True)
