// Copyright 2022-2026 Vector 35 Inc.
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

//! Interfaces for demangling and simplifying mangled names in binaries.

use binaryninjacore_sys::*;
use std::ffi::{c_char, c_void};

use crate::architecture::{ArchitectureExt, CoreArchitecture};
use crate::binary_view::BinaryView;
use crate::string::{raw_to_string, BnString, IntoCStr};
use crate::types::{QualifiedName, Type};

use crate::rc::*;

pub type Result<R> = std::result::Result<R, ()>;

const DEMANGLER_MSVC: &str = "msvc";
const DEMANGLER_GNU3: &str = "gnu3";
const DEMANGLER_LLVM: &str = "llvm";

fn collect_demangler_result(
    res: bool,
    result: &mut BNDemanglerResult,
) -> Option<(QualifiedName, Option<Ref<Type>>)> {
    match res {
        true => {
            let out_type = match result.type_.is_null() {
                true => None,
                false => Some(unsafe { Type::ref_from_raw(BNNewTypeReference(result.type_)) }),
            };
            let name = QualifiedName::from_raw(&result.name);
            unsafe { BNFreeDemanglerResult(result) };

            Some((name, out_type))
        }
        false => None,
    }
}

fn config_for_context(
    arch: &CoreArchitecture,
    view: Option<&BinaryView>,
    simplify: bool,
) -> BNDemanglerConfig {
    let platform = arch.standalone_platform();
    let mut config = match view {
        Some(v) => unsafe { BNGetDemanglerConfigForBinaryView(v.handle) },
        None => unsafe {
            BNGetDemanglerConfigForPlatform(
                platform
                    .as_ref()
                    .map(|p| p.handle)
                    .unwrap_or(std::ptr::null_mut()),
                simplify,
            )
        },
    };
    config.simplifyTemplates = simplify;
    config
}

fn demangle_with_named_demangler(
    demangler_name: &str,
    arch: &CoreArchitecture,
    mangled_name: &str,
    simplify: bool,
) -> Option<(QualifiedName, Option<Ref<Type>>)> {
    let demangler_name = demangler_name.to_cstr();
    let demangler = unsafe { BNGetDemanglerByName(demangler_name.as_ptr()) };
    if demangler.is_null() {
        return None;
    }

    let mangled_name = mangled_name.to_cstr();
    let mut config = config_for_context(arch, None, simplify);
    let mut result = BNDemanglerResult::default();
    let res = unsafe {
        BNDemangleWithDemangler(
            demangler,
            mangled_name.as_ptr(),
            &mut config,
            &mut result,
        )
    };
    collect_demangler_result(res, &mut result)
}

pub fn demangle_generic(
    arch: &CoreArchitecture,
    mangled_name: &str,
    view: Option<&BinaryView>,
    simplify: bool,
) -> Option<(QualifiedName, Option<Ref<Type>>)> {
    let mangled_name = mangled_name.to_cstr();
    let mut config = config_for_context(arch, view, simplify);
    let mut result = BNDemanglerResult::default();
    let res = unsafe { BNDemangle(mangled_name.as_ptr(), &mut config, &mut result) };
    collect_demangler_result(res, &mut result)
}

pub fn demangle_llvm(mangled_name: &str, simplify: bool) -> Option<QualifiedName> {
    let demangler_name = DEMANGLER_LLVM.to_cstr();
    let demangler = unsafe { BNGetDemanglerByName(demangler_name.as_ptr()) };
    if demangler.is_null() {
        return None;
    }

    let mangled_name = mangled_name.to_cstr();
    let mut config = unsafe { BNGetDefaultDemanglerConfig() };
    config.simplifyTemplates = simplify;
    let mut result = BNDemanglerResult::default();
    let res = unsafe {
        BNDemangleWithDemangler(demangler, mangled_name.as_ptr(), &mut config, &mut result)
    };
    collect_demangler_result(res, &mut result).map(|(name, _)| name)
}

pub fn demangle_gnu3(
    arch: &CoreArchitecture,
    mangled_name: &str,
    simplify: bool,
) -> Option<(QualifiedName, Option<Ref<Type>>)> {
    demangle_with_named_demangler(DEMANGLER_GNU3, arch, mangled_name, simplify)
}

pub fn demangle_ms(
    arch: &CoreArchitecture,
    mangled_name: &str,
    simplify: bool,
) -> Option<(QualifiedName, Option<Ref<Type>>)> {
    demangle_with_named_demangler(DEMANGLER_MSVC, arch, mangled_name, simplify)
}

#[derive(PartialEq, Eq, Hash)]
pub struct Demangler {
    pub(crate) handle: *mut BNDemangler,
}

impl Demangler {
    pub(crate) unsafe fn from_raw(handle: *mut BNDemangler) -> Self {
        debug_assert!(!handle.is_null());
        Self { handle }
    }

    pub fn list() -> Array<Self> {
        let mut count: usize = 0;
        let demanglers = unsafe { BNGetDemanglerList(&mut count) };
        unsafe { Array::<Demangler>::new(demanglers, count, ()) }
    }

    pub fn is_mangled_string(&self, name: &str) -> bool {
        let bytes = name.to_cstr();
        unsafe { BNIsDemanglerMangledName(self.handle, bytes.as_ref().as_ptr() as *const _) }
    }

    pub fn demangle(
        &self,
        arch: &CoreArchitecture,
        name: &str,
        view: Option<&BinaryView>,
        simplify: bool,
    ) -> Option<(QualifiedName, Option<Ref<Type>>)> {
        let name_bytes = name.to_cstr();

        let mut config = config_for_context(arch, view, simplify);
        let mut result = BNDemanglerResult::default();

        let res = unsafe {
            BNDemangleWithDemangler(
                self.handle,
                name_bytes.as_ref().as_ptr() as *const _,
                &mut config,
                &mut result,
            )
        };

        collect_demangler_result(res, &mut result)
    }

    pub fn name(&self) -> String {
        unsafe { BnString::into_string(BNGetDemanglerName(self.handle)) }
    }

    pub fn from_name(name: &str) -> Option<Self> {
        let name_bytes = name.to_cstr();
        let demangler = unsafe { BNGetDemanglerByName(name_bytes.as_ref().as_ptr() as *const _) };
        if demangler.is_null() {
            None
        } else {
            Some(unsafe { Demangler::from_raw(demangler) })
        }
    }

    pub fn register<C: CustomDemangler>(name: &str, demangler: C) -> Self {
        extern "C" fn cb_is_mangled_string<C>(ctxt: *mut c_void, name: *const c_char) -> bool
        where
            C: CustomDemangler,
        {
            ffi_wrap!("CustomDemangler::cb_is_mangled_string", unsafe {
                let cmd = &*(ctxt as *const C);
                let Some(name) = raw_to_string(name) else {
                    return false;
                };
                cmd.is_mangled_string(&name)
            })
        }
        extern "C" fn cb_demangle<C>(
            ctxt: *mut c_void,
            name: *const c_char,
            config: *const BNDemanglerConfig,
            result: *mut BNDemanglerResult,
        ) -> bool
        where
            C: CustomDemangler,
        {
            ffi_wrap!("CustomDemangler::cb_demangle", unsafe {
                if config.is_null() || result.is_null() {
                    return false;
                }

                let cmd = &*(ctxt as *const C);
                let Some(name) = raw_to_string(name) else {
                    return false;
                };
                let config = &*config;
                if config.platform.is_null() {
                    return false;
                }

                let arch = CoreArchitecture::from_raw(BNGetPlatformArchitecture(config.platform));
                let view = match config.view.is_null() {
                    false => Some(BinaryView::from_raw(config.view).to_owned()),
                    true => None,
                };

                match cmd.demangle(&arch, &name, view, config.simplifyTemplates) {
                    Some((name, ty)) => {
                        // NOTE: Leaked to the caller, who must pick the ref up.
                        (*result).type_ = match ty {
                            Some(t) => Ref::into_raw(t).handle,
                            None => std::ptr::null_mut(),
                        };
                        // NOTE: Leaked to be freed with `cb_free_result`.
                        (*result).name = QualifiedName::into_raw(name);
                        true
                    }
                    None => false,
                }
            })
        }

        extern "C" fn cb_free_result(_ctxt: *mut c_void, result: *mut BNDemanglerResult) {
            ffi_wrap!("CustomDemangler::cb_free_result", unsafe {
                if result.is_null() {
                    return;
                }
                if !(*result).type_.is_null() {
                    BNFreeType((*result).type_);
                    (*result).type_ = std::ptr::null_mut();
                }
                QualifiedName::free_raw((*result).name);
            })
        }

        let name = name.to_cstr();
        let name_ptr = name.as_ptr();
        let ctxt = Box::into_raw(Box::new(demangler));

        let callbacks = BNDemanglerCallbacks {
            size: std::mem::size_of::<BNDemanglerCallbacks>(),
            context: ctxt as *mut c_void,
            isMangledString: Some(cb_is_mangled_string::<C>),
            demangle: Some(cb_demangle::<C>),
            freeResult: Some(cb_free_result),
        };

        unsafe {
            Demangler::from_raw(BNRegisterDemangler(
                name_ptr,
                Box::leak(Box::new(callbacks)),
            ))
        }
    }

    pub fn promote(demangler: &Demangler) {
        unsafe {
            BNPromoteDemangler(demangler.handle);
        }
    }
}

unsafe impl Sync for Demangler {}

unsafe impl Send for Demangler {}

impl CoreArrayProvider for Demangler {
    type Raw = *mut BNDemangler;
    type Context = ();
    type Wrapped<'a> = Demangler;
}

unsafe impl CoreArrayProviderInner for Demangler {
    unsafe fn free(raw: *mut Self::Raw, _count: usize, _context: &Self::Context) {
        BNFreeDemanglerList(raw);
    }

    unsafe fn wrap_raw<'a>(raw: &'a Self::Raw, _context: &'a Self::Context) -> Self::Wrapped<'a> {
        Demangler::from_raw(*raw)
    }
}

pub trait CustomDemangler: 'static + Sync {
    fn is_mangled_string(&self, name: &str) -> bool;

    fn demangle(
        &self,
        arch: &CoreArchitecture,
        name: &str,
        view: Option<Ref<BinaryView>>,
        simplify: bool,
    ) -> Option<(QualifiedName, Option<Ref<Type>>)>;
}
