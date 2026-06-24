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

fn collect_demangled_type_name(
    res: bool,
    out_type: *mut BNType,
    mut out_name: *mut *mut std::os::raw::c_char,
    out_size: usize,
) -> Option<(QualifiedName, Option<Ref<Type>>)> {
    match res {
        true => {
            assert!(!out_name.is_null());
            let names: Vec<_> = unsafe { ArrayGuard::<BnString>::new(out_name, out_size, ()) }
                .iter()
                .map(str::to_string)
                .collect();
            unsafe { BNFreeDemangledName(&mut out_name, out_size) };

            let out_type = match out_type.is_null() {
                true => None,
                false => Some(unsafe { Type::ref_from_raw(out_type) }),
            };

            Some((names.into(), out_type))
        }
        false => None,
    }
}

pub fn demangle_generic(
    arch: &CoreArchitecture,
    mangled_name: &str,
    view: Option<&BinaryView>,
    simplify: bool,
) -> Option<(QualifiedName, Option<Ref<Type>>)> {
    let mangled_name = mangled_name.to_cstr();
    let mut out_type: *mut BNType = std::ptr::null_mut();
    let mut out_name = BNQualifiedName::default();
    let res = unsafe {
        BNDemangleGeneric(
            arch.handle,
            mangled_name.as_ptr(),
            &mut out_type,
            &mut out_name,
            view.map(|v| v.handle).unwrap_or(std::ptr::null_mut()),
            simplify,
        )
    };

    if res {
        let out_type = match out_type.is_null() {
            true => None,
            false => Some(unsafe { Type::ref_from_raw(out_type) }),
        };
        Some((QualifiedName::from_owned_raw(out_name), out_type))
    } else {
        None
    }
}

pub fn demangle_llvm(mangled_name: &str, simplify: bool) -> Option<QualifiedName> {
    let mangled_name = mangled_name.to_cstr();
    let mut out_name: *mut *mut std::os::raw::c_char = std::ptr::null_mut();
    let mut out_size: usize = 0;
    let res = unsafe {
        BNDemangleLLVM(
            mangled_name.as_ptr(),
            &mut out_name,
            &mut out_size,
            simplify,
        )
    };

    match res {
        true => {
            assert!(!out_name.is_null());
            let names: Vec<_> = unsafe { ArrayGuard::<BnString>::new(out_name, out_size, ()) }
                .iter()
                .map(str::to_string)
                .collect();
            unsafe { BNFreeDemangledName(&mut out_name, out_size) };

            Some(names.into())
        }
        false => None,
    }
}

pub fn demangle_gnu3(
    arch: &CoreArchitecture,
    mangled_name: &str,
    simplify: bool,
) -> Option<(QualifiedName, Option<Ref<Type>>)> {
    let mangled_name = mangled_name.to_cstr();
    let mut out_type: *mut BNType = std::ptr::null_mut();
    let mut out_name: *mut *mut std::os::raw::c_char = std::ptr::null_mut();
    let mut out_size: usize = 0;
    let res = unsafe {
        BNDemangleGNU3(
            arch.handle,
            mangled_name.as_ptr(),
            &mut out_type,
            &mut out_name,
            &mut out_size,
            simplify,
        )
    };

    collect_demangled_type_name(res, out_type, out_name, out_size)
}

pub fn demangle_ms(
    arch: &CoreArchitecture,
    mangled_name: &str,
    simplify: bool,
) -> Option<(QualifiedName, Option<Ref<Type>>)> {
    let mangled_name = mangled_name.to_cstr();
    let mut out_type: *mut BNType = std::ptr::null_mut();
    let mut out_name: *mut *mut std::os::raw::c_char = std::ptr::null_mut();
    let mut out_size: usize = 0;
    let res = unsafe {
        BNDemangleMS(
            arch.handle,
            mangled_name.as_ptr(),
            &mut out_type,
            &mut out_name,
            &mut out_size,
            simplify,
        )
    };

    collect_demangled_type_name(res, out_type, out_name, out_size)
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

        let mut result = BNDemanglerResult::default();

        let res = unsafe {
            BNDemanglerTryDemangle(
                self.handle,
                name_bytes.as_ref().as_ptr() as *const _,
                &mut config,
                &mut result,
            )
        };

        match res {
            true => {
                let var_type = match result.type_.is_null() {
                    true => None,
                    false => Some(unsafe { Type::ref_from_raw(BNNewTypeReference(result.type_)) }),
                };
                let name = QualifiedName::from_raw(&result.name);
                unsafe { BNFreeDemanglerResult(&mut result) };

                Some((name, var_type))
            }
            false => None,
        }
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
